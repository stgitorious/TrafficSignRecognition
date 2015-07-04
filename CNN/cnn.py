"""This tutorial introduces the LeNet5 neural network architecture
using Theano.  LeNet5 is a convolutional neural network, good for
classifying images. This tutorial shows how to build the architecture,
and comes with all the hyper-parameters you need to reproduce the
paper's MNIST results.


This implementation simplifies the model in the following ways:

 - LeNetConvPool doesn't implement location-specific gain and bias parameters
 - LeNetConvPool doesn't implement pooling by average, it implements pooling by max.
 - Digit classification is implemented with a logistic regression rather than an RBF network
 - LeNet5 was not fully-connected convolutions at second layer

References:
 - Y. LeCun, L. Bottou, Y. Bengio and P. Haffner:
   Gradient-Based Learning Applied to Document
   Recognition, Proceedings of the IEEE, 86(11):2278-2324, November 1998.
   http://yann.lecun.com/exdb/publis/pdf/lecun-98.pdf

"""
import os
import sys
import time

import numpy

import theano
import theano.tensor as T
from theano.tensor.signal import downsample
from theano.tensor.nnet import conv
import pickle

import logit
import utils
import conv
from mlp import HiddenLayer

def train_classifier(dataset_path, img_dim=28, learning_rate=0.1, n_epochs=200, kernel_dim=(5, 5), nkerns=(20, 50), mlp_layers=(500, 10), batch_size= 500, pool_size= (2, 2)):
    """ Demonstrates lenet on MNIST dataset

    :type learning_rate: float
    :param learning_rate: learning rate used (factor for the stochastic
                          gradient)

    :type n_epochs: int
    :param n_epochs: maximal number of epochs to run the optimizer

    :type dataset: string
    :param dataset: path to the dataset used for training /testing (MNIST here)

    :type nkerns: list of ints
    :param nkerns: number of kernels on each layer
    """

    rng = numpy.random.RandomState(23455)

    datasets = utils.load_data(dataset_path)

    train_set_x, train_set_y = datasets[0]
    valid_set_x, valid_set_y = datasets[1]
    test_set_x, test_set_y = datasets[2]

    # compute number of minibatches for training, validation and testing
    n_train_batches = train_set_x.get_value(borrow=True).shape[0]
    n_valid_batches = valid_set_x.get_value(borrow=True).shape[0]
    n_test_batches = test_set_x.get_value(borrow=True).shape[0]
    n_train_batches /= batch_size
    n_valid_batches /= batch_size
    n_test_batches /= batch_size

    # allocate symbolic variables for the data
    index = T.lscalar()  # index to a [mini]batch

    # start-snippet-1
    x = T.matrix('x')  # the data is presented as rasterized images
    y = T.ivector('y')  # the labels are presented as 1D vector of [int] labels

    ######################
    # BUILD ACTUAL MODEL #
    ######################
    print('... building the model')

    # Reshape matrix of rasterized images of shape (batch_size, 28 * 28)
    # to a 4D tensor, compatible with our LeNetConvPoolLayer
    # (28, 28) is the size of MNIST images.
    layer0_img_dim = img_dim # = 28 in case of mnist
    layer0_kernel_dim = kernel_dim[0]
    layer0_input = x.reshape((batch_size, 1, layer0_img_dim, layer0_img_dim))

    # Construct the first convolutional pooling layer:
    # filtering reduces the image size to (28-5+1 , 28-5+1) = (24, 24)
    # maxpooling reduces this further to (24/2, 24/2) = (12, 12)
    # 4D output tensor is thus of shape (batch_size, nkerns[0], 12, 12)
    layer0 = conv.ConvPoolLayer(
        rng,
        input=layer0_input,
        image_shape=(batch_size, 1, layer0_img_dim, layer0_img_dim),
        filter_shape=(nkerns[0], 1, layer0_kernel_dim, layer0_kernel_dim),
        poolsize= pool_size
    )

    # Construct the second convolutional pooling layer
    # filtering reduces the image size to (12-5+1, 12-5+1) = (8, 8)
    # maxpooling reduces this further to (8/2, 8/2) = (4, 4)
    # 4D output tensor is thus of shape (batch_size, nkerns[1], 4, 4)
    layer1_img_dim = int((layer0_img_dim - layer0_kernel_dim + 1)/2) # = 12 in case of mnist
    layer1_kernel_dim = kernel_dim[1]
    layer1 = conv.ConvPoolLayer(
        rng,
        input=layer0.output,
        image_shape=(batch_size, nkerns[0], layer1_img_dim, layer1_img_dim),
        filter_shape=(nkerns[1], nkerns[0], layer1_kernel_dim, layer1_kernel_dim),
        poolsize= pool_size
    )

    # the HiddenLayer being fully-connected, it operates on 2D matrices of
    # shape (batch_size, num_pixels) (i.e matrix of rasterized images).
    # This will generate a matrix of shape (batch_size, nkerns[1] * 4 * 4),
    # or (500, 50 * 4 * 4) = (500, 800) with the default values.
    layer2_input = layer1.output.flatten(2)

    # construct a fully-connected sigmoidal layer
    layer2_img_dim = int((layer1_img_dim - layer1_kernel_dim + 1)/2) # = 4 in case of mnist
    layer2 = HiddenLayer(
        rng,
        input=layer2_input,
        n_in=nkerns[1] * layer2_img_dim * layer2_img_dim,
        n_out=mlp_layers[0],
        activation=T.tanh
    )

    # classify the values of the fully-connected sigmoidal layer
    layer3 = logit.LogisticRegression(input=layer2.output, n_in=mlp_layers[0], n_out=mlp_layers[1])

    # the cost we minimize during training is the NLL of the model
    cost = layer3.negative_log_likelihood(y)

    # create a function to compute the mistakes that are made by the model
    test_model = theano.function(
        [index],
        layer3.errors(y),
        givens={
            x: test_set_x[index * batch_size: (index + 1) * batch_size],
            y: test_set_y[index * batch_size: (index + 1) * batch_size]
        }
    )

    validate_model = theano.function(
        [index],
        layer3.errors(y),
        givens={
            x: valid_set_x[index * batch_size: (index + 1) * batch_size],
            y: valid_set_y[index * batch_size: (index + 1) * batch_size]
        }
    )

    # create a list of all model parameters to be fit by gradient descent
    params = layer3.params + layer2.params + layer1.params + layer0.params

    # create a list of gradients for all model parameters
    grads = T.grad(cost, params)

    # train_model is a function that updates the model parameters by
    # SGD Since this model has many parameters, it would be tedious to
    # manually create an update rule for each model parameter. We thus
    # create the updates list by automatically looping over all
    # (params[i], grads[i]) pairs.
    updates = [(param_i, param_i - learning_rate * grad_i) for param_i, grad_i in zip(params, grads)]

    train_model = theano.function(
        [index],
        cost,
        updates=updates,
        givens={
            x: train_set_x[index * batch_size: (index + 1) * batch_size],
            y: train_set_y[index * batch_size: (index + 1) * batch_size]
        }
    )
    # end-snippet-1

    ###############
    # TRAIN MODEL #
    ###############
    print('... training')
    # early-stopping parameters
    patience = 10000  # look as this many examples regardless
    patience_increase = 2  # wait this much longer when a new best is found
    improvement_threshold = 0.995  # a relative improvement of this much is considered significant
    validation_frequency = min(n_train_batches, patience / 2)
    # go through this many
    # minibatches before checking the network
    # on the validation set; in this case we
    # check every epoch

    best_validation_loss = numpy.inf
    best_iter = 0
    test_score = 0.
    start_time = time.clock()

    epoch = 0
    done_looping = False

    while (epoch < n_epochs) and (not done_looping):

        epoch += 1
        print("... epoch: %d" % epoch)

        for minibatch_index in range(int( n_train_batches)):

            iter = (epoch - 1) * n_train_batches + minibatch_index

            if iter % 100 == 0:
                print('... training @ iter = %.0f' % iter)

            # train the minibatch
            cost_ij = train_model(minibatch_index)

            if (iter + 1) % validation_frequency == 0:

                # compute zero-one loss on validation set
                validation_losses = [validate_model(i) for i in range(int(n_valid_batches))]
                this_validation_loss = numpy.mean(validation_losses)
                print('... epoch %d, minibatch %d/%d, validation error %.2f %%' % (epoch, minibatch_index + 1, n_train_batches, this_validation_loss * 100.))

                # if we got the best validation score until now
                if this_validation_loss < best_validation_loss:

                    # improve patience if loss improvement is good enough
                    if this_validation_loss < best_validation_loss * improvement_threshold:
                        patience = max(patience, iter * patience_increase)

                    # save best validation score and iteration number
                    best_validation_loss = this_validation_loss
                    best_iter = iter

                    # test it on the test set
                    test_losses = [ test_model(i) for i in range(int(n_test_batches))]
                    test_score = numpy.mean(test_losses)
                    print(('    epoch %i, minibatch %i/%i, test error of best model %.2f%%') % (epoch, minibatch_index + 1, n_train_batches, test_score * 100.))

            if patience <= iter:
                done_looping = True
                break

    end_time = time.clock()
    print('Optimization complete.')
    print('Best validation score of %.2f%% obtained at iteration %i with test performance %.2f%%' % (best_validation_loss * 100., best_iter + 1, test_score * 100.))
    print('The code for file ' + os.path.split(__file__)[1] + ' ran for %.2fm' % ((end_time - start_time) / 60.))
    print(sys.stderr)

    return

    # serialize the params of the model
    # the -1 is for HIGHEST_PROTOCOL
    # this will overwrite current contents and it triggers much more efficient storage than numpy's default
    save_file = open('D:\\_Dataset\\cnn_model_classifier.pkl', 'wb')
    pickle.dump(dataset_path, save_file, -1)
    pickle.dump(img_dim, save_file, -1)
    pickle.dump(kernel_dim, save_file, -1)
    pickle.dump(nkerns, save_file, -1)
    pickle.dump(mlp_layers, save_file, -1)
    pickle.dump(pool_size, save_file, -1)
    pickle.dump(layer0.W.get_value(borrow=True), save_file, -1)
    pickle.dump(layer0.b.get_value(borrow=True), save_file, -1)
    pickle.dump(layer1.W.get_value(borrow=True), save_file, -1)
    pickle.dump(layer1.b.get_value(borrow=True), save_file, -1)
    pickle.dump(layer2.W.get_value(borrow=True), save_file, -1)
    pickle.dump(layer2.b.get_value(borrow=True), save_file, -1)
    pickle.dump(layer3.W.get_value(borrow=True), save_file, -1)
    pickle.dump(layer3.b.get_value(borrow=True), save_file, -1)
    save_file.close()

def train_detector(dataset_path, img_dim=28, learning_rate=0.1, n_epochs=200, kernel_dim=(5, 5), nkerns=(20, 50), mlp_layers=(500, 10), batch_size= 500, pool_size= (2, 2)):
    """ Demonstrates lenet on MNIST dataset

    :type learning_rate: float
    :param learning_rate: learning rate used (factor for the stochastic
                          gradient)

    :type n_epochs: int
    :param n_epochs: maximal number of epochs to run the optimizer

    :type dataset: string
    :param dataset: path to the dataset used for training /testing (MNIST here)

    :type nkerns: list of ints
    :param nkerns: number of kernels on each layer
    """

    rng = numpy.random.RandomState(23455)

    datasets = utils.load_data(dataset_path)

    train_set_x, train_set_y = datasets[0]
    valid_set_x, valid_set_y = datasets[1]
    test_set_x, test_set_y = datasets[2]

    # compute number of minibatches for training, validation and testing
    n_train_batches = train_set_x.get_value(borrow=True).shape[0]
    n_valid_batches = valid_set_x.get_value(borrow=True).shape[0]
    n_test_batches = test_set_x.get_value(borrow=True).shape[0]
    n_train_batches /= batch_size
    n_valid_batches /= batch_size
    n_test_batches /= batch_size

    # allocate symbolic variables for the data
    index = T.lscalar()  # index to a [mini]batch

    # start-snippet-1
    x = T.matrix('x')  # the data is presented as rasterized images
    y = T.ivector('y')  # the labels are presented as 1D vector of [int] labels

    ######################
    # BUILD ACTUAL MODEL #
    ######################
    print('... building the model')

    # Reshape matrix of rasterized images of shape (batch_size, 28 * 28)
    # to a 4D tensor, compatible with our LeNetConvPoolLayer
    # (28, 28) is the size of MNIST images.
    layer0_img_dim = img_dim # = 28 in case of mnist
    layer0_kernel_dim = kernel_dim[0]
    layer0_input = x.reshape((batch_size, 1, layer0_img_dim, layer0_img_dim))

    # Construct the first convolutional pooling layer:
    # filtering reduces the image size to (28-5+1 , 28-5+1) = (24, 24)
    # maxpooling reduces this further to (24/2, 24/2) = (12, 12)
    # 4D output tensor is thus of shape (batch_size, nkerns[0], 12, 12)
    layer0 = conv.ConvPoolLayer(
        rng,
        input=layer0_input,
        image_shape=(batch_size, 1, layer0_img_dim, layer0_img_dim),
        filter_shape=(nkerns[0], 1, layer0_kernel_dim, layer0_kernel_dim),
        poolsize= pool_size
    )

    # Construct the second convolutional pooling layer
    # filtering reduces the image size to (12-5+1, 12-5+1) = (8, 8)
    # maxpooling reduces this further to (8/2, 8/2) = (4, 4)
    # 4D output tensor is thus of shape (batch_size, nkerns[1], 4, 4)
    layer1_img_dim = int((layer0_img_dim - layer0_kernel_dim + 1)/2) # = 12 in case of mnist
    layer1_kernel_dim = kernel_dim[1]
    layer1 = conv.ConvPoolLayer(
        rng,
        input=layer0.output,
        image_shape=(batch_size, nkerns[0], layer1_img_dim, layer1_img_dim),
        filter_shape=(nkerns[1], nkerns[0], layer1_kernel_dim, layer1_kernel_dim),
        poolsize= pool_size
    )

    # the HiddenLayer being fully-connected, it operates on 2D matrices of
    # shape (batch_size, num_pixels) (i.e matrix of rasterized images).
    # This will generate a matrix of shape (batch_size, nkerns[1] * 4 * 4),
    # or (500, 50 * 4 * 4) = (500, 800) with the default values.
    layer2_input = layer1.output.flatten(2)

    # construct a fully-connected sigmoidal layer
    layer2_img_dim = int((layer1_img_dim - layer1_kernel_dim + 1)/2) # = 4 in case of mnist
    layer2 = HiddenLayer(
        rng,
        input=layer2_input,
        n_in=nkerns[1] * layer2_img_dim * layer2_img_dim,
        n_out=mlp_layers[0],
        activation=T.tanh
    )

    # classify the values of the fully-connected sigmoidal layer
    layer3 = logit.LogisticRegression(input=layer2.output, n_in=mlp_layers[0], n_out=mlp_layers[1])

    # the cost we minimize during training is the NLL of the model
    cost = layer3.negative_log_likelihood(y)

    # create a function to compute the mistakes that are made by the model
    test_model = theano.function(
        [index],
        layer3.errors(y),
        givens={
            x: test_set_x[index * batch_size: (index + 1) * batch_size],
            y: test_set_y[index * batch_size: (index + 1) * batch_size]
        }
    )

    validate_model = theano.function(
        [index],
        layer3.errors(y),
        givens={
            x: valid_set_x[index * batch_size: (index + 1) * batch_size],
            y: valid_set_y[index * batch_size: (index + 1) * batch_size]
        }
    )

    # create a list of all model parameters to be fit by gradient descent
    params = layer3.params + layer2.params + layer1.params + layer0.params

    # create a list of gradients for all model parameters
    grads = T.grad(cost, params)

    # train_model is a function that updates the model parameters by
    # SGD Since this model has many parameters, it would be tedious to
    # manually create an update rule for each model parameter. We thus
    # create the updates list by automatically looping over all
    # (params[i], grads[i]) pairs.
    updates = [(param_i, param_i - learning_rate * grad_i) for param_i, grad_i in zip(params, grads)]

    train_model = theano.function(
        [index],
        cost,
        updates=updates,
        givens={
            x: train_set_x[index * batch_size: (index + 1) * batch_size],
            y: train_set_y[index * batch_size: (index + 1) * batch_size]
        }
    )
    # end-snippet-1

    ###############
    # TRAIN MODEL #
    ###############
    print('... training')
    # early-stopping parameters
    patience = 10000  # look as this many examples regardless
    patience_increase = 2  # wait this much longer when a new best is found
    improvement_threshold = 0.995  # a relative improvement of this much is considered significant
    validation_frequency = min(n_train_batches, patience / 2)
    # go through this many
    # minibatches before checking the network
    # on the validation set; in this case we
    # check every epoch

    best_validation_loss = numpy.inf
    best_iter = 0
    test_score = 0.
    start_time = time.clock()

    epoch = 0
    done_looping = False

    while (epoch < n_epochs) and (not done_looping):

        epoch += 1
        print("... epoch: %d" % epoch)

        for minibatch_index in range(int( n_train_batches)):

            iter = (epoch - 1) * n_train_batches + minibatch_index

            if iter % 100 == 0:
                print('... training @ iter = %.0f' % iter)

            # train the minibatch
            cost_ij = train_model(minibatch_index)

            if (iter + 1) % validation_frequency == 0:

                # compute zero-one loss on validation set
                validation_losses = [validate_model(i) for i in range(int(n_valid_batches))]
                this_validation_loss = numpy.mean(validation_losses)
                print('... epoch %d, minibatch %d/%d, validation error %.2f %%' % (epoch, minibatch_index + 1, n_train_batches, this_validation_loss * 100.))

                # if we got the best validation score until now
                if this_validation_loss < best_validation_loss:

                    # improve patience if loss improvement is good enough
                    if this_validation_loss < best_validation_loss * improvement_threshold:
                        patience = max(patience, iter * patience_increase)

                    # save best validation score and iteration number
                    best_validation_loss = this_validation_loss
                    best_iter = iter

                    # test it on the test set
                    test_losses = [ test_model(i) for i in range(int(n_test_batches))]
                    test_score = numpy.mean(test_losses)
                    print(('    epoch %i, minibatch %i/%i, test error of best model %.2f%%') % (epoch, minibatch_index + 1, n_train_batches, test_score * 100.))

            if patience <= iter:
                done_looping = True
                break

    end_time = time.clock()
    print('Optimization complete.')
    print('Best validation score of %.2f%% obtained at iteration %i with test performance %.2f%%' % (best_validation_loss * 100., best_iter + 1, test_score * 100.))
    print('The code for file ' + os.path.split(__file__)[1] + ' ran for %.2fm' % ((end_time - start_time) / 60.))
    print(sys.stderr)

    return

    # serialize the params of the model
    # the -1 is for HIGHEST_PROTOCOL
    # this will overwrite current contents and it triggers much more efficient storage than numpy's default
    save_file = open('D:\\_Dataset\\cnn_model.pkl', 'wb')
    pickle.dump(dataset_path, save_file, -1)
    pickle.dump(img_dim, save_file, -1)
    pickle.dump(kernel_dim, save_file, -1)
    pickle.dump(nkerns, save_file, -1)
    pickle.dump(mlp_layers, save_file, -1)
    pickle.dump(pool_size, save_file, -1)
    pickle.dump(layer0.W.get_value(borrow=True), save_file, -1)
    pickle.dump(layer0.b.get_value(borrow=True), save_file, -1)
    pickle.dump(layer1.W.get_value(borrow=True), save_file, -1)
    pickle.dump(layer1.b.get_value(borrow=True), save_file, -1)
    pickle.dump(layer2.W.get_value(borrow=True), save_file, -1)
    pickle.dump(layer2.b.get_value(borrow=True), save_file, -1)
    pickle.dump(layer3.W.get_value(borrow=True), save_file, -1)
    pickle.dump(layer3.b.get_value(borrow=True), save_file, -1)
    save_file.close()

def classify_img_from_file(path, img_dim=28):

    # this is how to prepare an image to be used by the CNN model
    import PIL
    import PIL.Image
    img = PIL.Image.open(path)
    img = numpy.asarray(img, dtype='float64') / 256.0
    img4D = img.reshape(1, 1, img_dim, img_dim)

    return __classify_img(img4D)

def classify_img_from_dataset(dataset_path, index, img_dim=28):

    data = pickle.load(open(dataset_path, 'rb'))
    img = data[0][0][index]
    del data
    img4D = img.reshape(1, 1, img_dim, img_dim)

    return __classify_img(img)

    # this is if image is loaded from tensor dataset
    #img = test_set_x[index]
    #img = img.eval()
    #img4D = img.reshape(1, 1, img_dim, img_dim)

def __classify_img(img4D):

    save_file = open('D:\\_Dataset\\cnn_model_detector.pkl', 'rb')
    loaded_objects = []
    for i in range(14):
        loaded_objects.append(pickle.load(save_file))
    save_file.close()

    img_dim = loaded_objects[1]
    kernel_dim = loaded_objects[2]
    nkerns = loaded_objects[3]
    mlp_layers = loaded_objects[4]
    pool_size = loaded_objects[5]

    layer0_W = theano.shared(loaded_objects[6], borrow=True)
    layer0_b = theano.shared(loaded_objects[7], borrow=True)
    layer1_W = theano.shared(loaded_objects[8], borrow=True)
    layer1_b = theano.shared(loaded_objects[9], borrow=True)
    layer2_W = theano.shared(loaded_objects[10], borrow=True)
    layer2_b = theano.shared(loaded_objects[11], borrow=True)
    layer3_W = theano.shared(loaded_objects[12], borrow=True)
    layer3_b = theano.shared(loaded_objects[13], borrow=True)

    layer0_img_dim = img_dim # = 28 in case of mnist
    layer0_kernel_dim = kernel_dim[0]
    layer1_img_dim = int((layer0_img_dim - layer0_kernel_dim + 1)/2) # = 12 in case of mnist
    layer1_kernel_dim = kernel_dim[1]
    layer2_img_dim = int((layer1_img_dim - layer1_kernel_dim + 1)/2) # = 4 in case of mnist

    start_time = time.clock()

    # layer 0: Conv-Pool
    filter_shape = (nkerns[0], 1, layer0_kernel_dim, layer0_kernel_dim)
    image_shape = (1, 1, layer0_img_dim, layer0_img_dim)
    (layer0_filters, layer0_output) = conv.filter_image(img=img4D, W=layer0_W, b=layer0_b, image_shape=image_shape, filter_shape=filter_shape, pool_size=pool_size)

    # layer 1: Conv-Pool
    filter_shape = (nkerns[1], nkerns[0], layer1_kernel_dim, layer1_kernel_dim)
    image_shape = (1, nkerns[0], layer1_img_dim, layer1_img_dim)
    (layer1_filters, layer1_output) = conv.filter_image(img=layer0_filters, W=layer1_W, b=layer1_b, image_shape=image_shape, filter_shape=filter_shape, pool_size=pool_size)

    # layer 2,3: MLP (hidden + logit)
    n_in = nkerns[1] * layer2_img_dim * layer2_img_dim
    n_out = mlp_layers[0]
    classification_result = logit.classify_images(input=layer1_output, filters=layer1_filters, W1=layer2_W, b1=layer2_b, W2=layer3_W, b2=layer3_b, n_in=n_in, n_out=n_out)

    end_time = time.clock()

    #__plot_filters_1(img4D, 1)
    #__plot_filters_1(layer0_filters, 2)
    #__plot_filters_1(layer1_filters, 3)
    #__plot_filters_2(loaded_objects[6], 4)
    #__plot_filters_2(loaded_objects[8], 5)

    print('Classification result: %d in %f sec.' % (classification_result, (end_time - start_time)))
    print(classification_result)

    return classification_result

def __plot_filters_1(filters, figure_num):

    import matplotlib.pyplot as plt

    # plot original image and first and second components of output
    plt.figure(figure_num)
    plt.gray()
    plt.ion()
    length = filters.shape[1]
    for i in range(0, length):
        plt.subplot(1, length, i + 1)
        plt.axis('off')
        plt.imshow(filters[0, i, :, :])
    plt.show()

def __plot_filters_2(filters, figure_num):

    import matplotlib.pyplot as plt

    # plot original image and first and second components of output
    plt.figure(figure_num)
    plt.gray()
    plt.ion()
    length = filters.shape[0]
    for i in range(0, length):
        plt.subplot(1, length, i + 1)
        plt.axis('off')
        plt.imshow(filters[i, 0, :, :])
    plt.show()
