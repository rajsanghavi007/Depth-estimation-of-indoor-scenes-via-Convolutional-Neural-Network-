# -*- coding: utf-8 -*-
"""DL_Code_Final.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1vQttAM0xt8GCmtBQjqJKJagBFrIqZ0Rc
"""

import os
import math
import numpy as np
import tensorflow as tf
from matplotlib import image
import matplotlib.pyplot as plt
from sklearn.utils import shuffle
from tensorflow.keras.layers import Conv2D, UpSampling2D, LeakyReLU, Concatenate, MaxPool2D, Input
from tensorflow.keras import Model
from tensorflow.keras.applications import DenseNet169
import tensorflow.keras.backend as K
# Set up env parameters to force training on GPU
os.environ["CUDA_DEVICE_ORDER"]="PCI_BUS_ID"
os.environ["CUDA_VISIBLE_DEVICES"]="0,1"

with tf.device(tf.DeviceSpec(device_type="GPU", device_index=1)):
    if tf.test.gpu_device_name():
        print('Default GPU Device: {}'.format(tf.test.gpu_device_name()))
    else:
        print("Please install GPU version of TF")

###########################
# Load Training Data Method
##########################
def load_data(filenames, labels):
    # Read images from disk
    images = []
    depth_labels = []
    for filename, label in zip(filenames, labels):
        image_decoded = tf.image.decode_jpeg(tf.io.read_file(train_path + filename))
        depth_resized = tf.image.resize(tf.image.decode_jpeg(tf.io.read_file(train_path + label)),
                                        [shape_depth[0], shape_depth[1]])

        # Format
        rgb = tf.image.convert_image_dtype(image_decoded, dtype=tf.float32)
        depth = tf.image.convert_image_dtype(depth_resized / 255.0, dtype=tf.float32)

        # Normalize the depth values (in cm)
        depth = 1000 / tf.clip_by_value(depth * 1000, 10, 1000)

        images.append(rgb)
        depth_labels.append(depth)

    images = tf.convert_to_tensor(images)
    depth_labels = tf.convert_to_tensor(depth_labels)

    return images, depth_labels

def _parse_function(filename, label): 
        # Read images from disk

        
        image_decoded = tf.image.decode_jpeg(tf.io.read_file(train_path + filename))
        depth_resized = tf.image.resize(tf.image.decode_jpeg(tf.io.read_file(train_path + label)), [shape_depth[0], shape_depth[1]])

        # Format
        rgb = tf.image.convert_image_dtype(image_decoded, dtype=tf.float32)
        depth = tf.image.convert_image_dtype(depth_resized / 255.0, dtype=tf.float32)
        
        # Normalize the depth values (in cm)
        depth = 1000 / tf.clip_by_value(depth * 1000, 10, 1000)

        return rgb, depth

######################
# Import Data From Local Machine
# Define filenames & labels
# Create DataSet with Augmentation
######################
# Define data import functionality
train_path = "D:/raj/DL_project/subset/"
train_csv = open(r"D:\raj\DL_project\subset\data\nyu2_train.csv", 'r').read()
nyu2_train = list((row.split(',') for row in (train_csv).split('\n') if len(row) > 0))
nyu2_train = shuffle(nyu2_train, random_state=0)

file_names = [i[0] for i in nyu2_train[:200]]  # the number of image is 1000
labels = [i[1] for i in nyu2_train[:200]]  # the number of image is 1000

shape_rgb = (480, 640, 3)
shape_depth = (240, 320, 1) # reduced resolution
batch_size = 8
learning_rate = 0.0001
epochs = 5

# Load data & ImageGenerator
X_train, Y_train = load_data(file_names, labels)
data_gen = tf.keras.preprocessing.image.ImageDataGenerator(horizontal_flip=True, channel_shift_range=0.75)
data_gen.fit(X_train)
data_gen.fit(Y_train)
dataset_iterator = data_gen.flow(X_train, Y_train, batch_size=batch_size)

###############################
# View Imgaes from the Data Generator
###############################
w = 10
h = 10
fig = plt.figure(figsize=(batch_size, batch_size))
for i in range(1, batch_size*batch_size + 1):
    im, label = dataset_iterator.next()
    fig.add_subplot(batch_size, batch_size, i)
    plt.axis('off')
    plt.imshow(im[0])
plt.show()

###########################
# CREATE MODEL STRUCTURE
###########################
from tensorflow.keras.layers import Conv2D, UpSampling2D, LeakyReLU, Concatenate, MaxPooling2D
from tensorflow.keras import Model
from tensorflow.keras.applications import DenseNet169


class UpscaleBlock(Model):
    def __init__(self, filters, name):
        super(UpscaleBlock, self).__init__()
        self.up = UpSampling2D(size=(2, 2), interpolation='bilinear', name=name + '_upsampling2d')
        self.concat = Concatenate(name=name + '_concat')  # Skip connection
        self.convA = Conv2D(filters=filters, kernel_size=3, strides=1, padding='same', name=name + '_convA')
        self.reluA = LeakyReLU(alpha=0.2)
        self.maxA = MaxPooling2D((2, 2))
        self.convB = Conv2D(filters=filters, kernel_size=3, strides=1, padding='same', name=name + '_convB')
        self.upscaleB = UpSampling2D(size=(2, 2), interpolation='bilinear')
        self.reluB = LeakyReLU(alpha=0.2)

    def call(self, x):
        b = self.reluB(self.upscaleB(self.convB(self.maxA(self.reluA(self.convA(self.concat([self.up(x[0]), x[1]])))))))
        return b


class Encoder(Model):
    def __init__(self):
        super(Encoder, self).__init__()
        self.base_model = DenseNet169(input_shape=(None, None, 3), include_top=False, weights='imagenet')
        print('Base model loaded {}'.format(DenseNet169.__name__))

        # Create encoder model that produce final features along with multiple intermediate features
        outputs = [self.base_model.outputs[-1]]
        for name in ['pool1', 'pool2_pool', 'pool3_pool', 'conv1/relu']: outputs.append(
            self.base_model.get_layer(name).output)
        self.encoder = Model(inputs=self.base_model.inputs, outputs=outputs)

    def call(self, x):
        return self.encoder(x)


class Decoder(Model):
    def __init__(self, decode_filters):
        super(Decoder, self).__init__()
        self.conv2 = Conv2D(filters=decode_filters, kernel_size=1, padding='same', name='conv2')
        self.up1 = UpscaleBlock(filters=decode_filters // 2, name='up1')
        self.up2 = UpscaleBlock(filters=decode_filters // 4, name='up2')
        self.up3 = UpscaleBlock(filters=decode_filters // 8, name='up3')
        self.up4 = UpscaleBlock(filters=decode_filters // 16, name='up4')
        self.conv3 = Conv2D(filters=1, kernel_size=3, strides=1, padding='same', name='conv3')

    def call(self, features):
        x, pool1, pool2, pool3, conv1 = features[0], features[1], features[2], features[3], features[4]
        up0 = self.conv2(x)
        up1 = self.up1([up0, pool3])
        up2 = self.up2([up1, pool2])
        up3 = self.up3([up2, pool1])
        up4 = self.up4([up3, conv1])
        return self.conv3(up4)


class DepthEstimate(Model):
    def __init__(self):
        super(DepthEstimate, self).__init__()
        self.encoder = Encoder()
        self.decoder = Decoder(decode_filters=int(self.encoder.layers[-1].output[0].shape[-1] // 2))
        print('\nModel created for Depth Estimation.')

    def call(self, x):
        return self.decoder(self.encoder(x))

#########################
# Define loss function
#########################
def depth_loss_function(y_true, y_pred, theta=0.1, maxDepthVal=1000.0 / 10.0):
    # Point-wise depth
    l_depth = K.mean(K.abs(y_pred - y_true), axis=-1)

    # Edges
    dy_true, dx_true = tf.image.image_gradients(y_true)
    dy_pred, dx_pred = tf.image.image_gradients(y_pred)
    l_edges = K.mean(K.abs(dy_pred - dy_true) + K.abs(dx_pred - dx_true), axis=-1)

    # Structural similarity (SSIM) index
    l_ssim = K.clip((1 - tf.image.ssim(y_true, y_pred, maxDepthVal)) * 0.5, 0, 1)

    # Weights
    w1 = 1.0
    w2 = 1.0
    w3 = theta

    return (w1 * l_ssim) + (w2 * K.mean(l_edges)) + (w3 * K.mean(l_depth))

#######################################
# Add Predition and Evaluation Fuctions
#######################################
def DepthNorm(x, maxDepth):
    return maxDepth / x


def predict(model, images, minDepth=10, maxDepth=1000, batch_size=2):
    # Support multiple RGBs, one RGB image, even grayscale
    if len(images.shape) < 3: images = np.stack((images, images, images), axis=2)
    if len(images.shape) < 4: images = images.reshape((1, images.shape[0], images.shape[1], images.shape[2]))
    # Compute predictions
    predictions = model.predict(images, batch_size=batch_size)
    # Put in expected range
    return np.clip(DepthNorm(predictions, maxDepth=1000), minDepth, maxDepth) / maxDepth


def scale_up(scale, images):
    from skimage.transform import resize
    scaled = []

    for i in range(len(images)):
        img = images[i]
        output_shape = (scale * img.shape[0], scale * img.shape[1])
        scaled.append(resize(img, output_shape, order=1, preserve_range=True, mode='reflect', anti_aliasing=True))

    return np.stack(scaled)


def evaluate(model, rgb, depth, batch_size=6):
    def compute_errors(gt, pred):
        thresh = np.maximum((gt / pred), (pred / gt))

        a1 = (thresh < 1.25).mean()
        a2 = (thresh < 1.25 ** 2).mean()
        a3 = (thresh < 1.25 ** 3).mean()

        abs_rel = np.mean(np.abs(gt - pred) / gt)

        rmse = (gt - pred) ** 2
        rmse = np.sqrt(rmse.mean())

        log_10 = (np.abs(np.log10(gt) - np.log10(pred))).mean()

        return a1, a2, a3, abs_rel, rmse, log_10

    depth_scores = np.zeros((6, len(rgb)))  # six metrics

    bs = batch_size

    for i in range(len(rgb) // bs):
        x = rgb[(i) * bs:(i + 1) * bs, :, :, :]

        # Compute results
        true_y = depth[(i) * bs:(i + 1) * bs, :, :]

        true_y = scale_up(2, true_y)

        pred_y = scale_up(2, predict(model, x / 255, minDepth=10, maxDepth=1000, batch_size=bs)[:, :, :, 0]) * 10.0
        

        # Compute errors per image in batch

        for j in range(len(true_y)):

            
            errors = compute_errors(true_y[j], (0.5 * pred_y[j]))

            for k in range(len(errors)):
                depth_scores[k][(i * bs) + j] = errors[k]

                # print(depth_scores)

    e = (depth_scores).mean(axis=1)

    print("{:>10}, {:>10}, {:>10}, {:>10}, {:>10}, {:>10}".format('a1', 'a2', 'a3', 'rel', 'rms', 'log_10'))
    print("{:10.4f}, {:10.4f}, {:10.4f}, {:10.4f}, {:10.4f}, {:10.4f}".format(e[0], e[1], e[2], e[3], e[4], e[5]))

###############################
# Training The Pre-Trained Model 
###############################
import os, sys, glob, time, pathlib, argparse

model = DepthEstimate()

checkpoint_path = "training_3/cp.ckpt"
checkpoint_dir = os.path.dirname(checkpoint_path)
cp_callback = tf.keras.callbacks.ModelCheckpoint(checkpoint_path, save_weights_only=True, verbose=1)

optimizer = tf.keras.optimizers.Adam(lr=learning_rate, amsgrad=True)

model.compile(loss=depth_loss_function, optimizer=optimizer)

# Calculate steps per epoch
spe = int(math.ceil((1. * len(file_names)) / batch_size)) 
model_history = model.fit(dataset_iterator, epochs=epochs, steps_per_epoch=spe)
model.save('D:\\kjumi\\DL_project\\assets' ,save_format='tf') # Saving the model

#############################################
# Evaluating the Model: 6 Evaluation Metrics
#############################################

test_csv = open(r"D:\kjumi\DL_project\subset\data\nyu2_test.csv", 'r').read()
nyu2_test = list((row.split(',') for row in (test_csv).split('\n') if len(row) > 0))
nyu2_test = shuffle(nyu2_test, random_state=0)

subtest = 100
# A vector of RGB filenames.
file_test = [i[0] for i in nyu2_test[:subtest]]     

#file = train_path+file_names[0]

# A vector of depth filenames.
ground_truth = [i[1] for i in nyu2_test[:subtest]] 
rgb = []
depth = []

for i in range(0, len(file_test)):
    f = file_test[i]
    g = ground_truth[i]    
    result = _parse_function(f, g)     
    rgb.append(result[0])    
    depth.append(result[1])    
rgb = tf.convert_to_tensor(rgb)
depth = tf.convert_to_tensor(depth)    
depth = depth[:,:,:,0]

evaluate(model, rgb, depth)

#############################################
# Construct a Simple CNN model For Comparison
#############################################

inputLayer=Input(shape=(None,None,3))
tmp=Conv2D(512,(7,7),activation='relu', padding='same',input_shape=(None,None,3))(inputLayer)
tmp=MaxPool2D((2,2))(tmp)
tmp=Conv2D(filters=216, kernel_size=3, strides=1, padding='same')(tmp)
tmp=MaxPool2D((2,2))(tmp)
tmp=Conv2D(filters=128, kernel_size=3, strides=1, padding='same')(tmp)
tmp=MaxPool2D((2,2))(tmp)
tmp=Conv2D(filters=512, kernel_size=3, strides=1, padding='same')(tmp)
tmp=UpSampling2D(size=(2, 2), interpolation='bilinear')(tmp)
tmp=Conv2D(filters=216, kernel_size=3, strides=1, padding='same')(tmp)
tmp=UpSampling2D(size=(2, 2), interpolation='bilinear')(tmp)
tmp=Conv2D(filters =128, kernel_size=3, strides=1, padding='same')(tmp)
outputLayer=Conv2D(filters=1, kernel_size=3, strides=1, padding='same')(tmp)
network=Model(inputLayer,outputLayer)

###############################
# Training The Simple CNN Model
###############################

import os
import tensorflow
checkpoint_path = "training_4/cp.ckpt"
checkpoint_dir = os.path.dirname(checkpoint_path)
cp_callback = tensorflow.keras.callbacks.ModelCheckpoint(checkpoint_path, save_weights_only=True, verbose=1)
optimizer = tensorflow.keras.optimizers.Adam(lr=learning_rate, amsgrad=True)
network.compile(loss= depth_loss_function, optimizer='adam')

# Calculate steps per epoch
spe = int(math.ceil((1. * len(file_names)) / batch_size)) 

network.fit(dataset_iterator, epochs=epochs, steps_per_epoch=spe, callbacks=[cp_callback])
network.save('aug_simple_cnn.h5') # saving the model





