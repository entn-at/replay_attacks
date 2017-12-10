
#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
Train a Convolutional Neural Network for detecting between replayed and genuine speech.
'''

# Load standard modules
from __future__ import print_function
import sys
import os
import io
import shutil
import numpy as np
import tensorflow as tf
from datetime import datetime
import math

from optparse import OptionParser

# Load userdefined modules
import audio
import dataset
import nn_architecture
import nn_architecture_rus as nn_r
import nn_architecture_birds as nn_b

import extract_cnn_scores_and_features as extractor
from utility import create_directory

## Good TF tutorial to look at 
# https://github.com/tensorflow/tensorflow/blob/master/tensorflow/examples/speech_commands/models.py
#----------------------------------------------------------------------------------------------------------------
def load_model(save_path, n_model=None):
    
    print('Loading model parameters ...')
    sess = tf.Session(config=tf.ConfigProto(allow_soft_placement=True))
    saver = tf.train.Saver()
    
    if n_model==None:        
        #path = tf.train.latest_checkpoint(save_path)
        path = os.path.join(save_path,"bestModel.ckpt")
    else:        
        path = os.path.join(save_path,"model.ckpt-"+str(n_model))
        
    saver.restore(sess, path)
    
    return sess, saver

#----------------------------------------------------------------------------------------------------------------
def compute_cross_entropy(true_labels, prediction, weights, regularize, lossPenalty, deviceId="/gpu:0"): 
    #the prediction must be raw outputs of the last layer without activation
    
    with tf.device(deviceId):  #"/gpu:0"
        with tf.name_scope('cross_entropy'):
            diff = tf.nn.softmax_cross_entropy_with_logits(labels=true_labels, logits=prediction)
            
            with tf.name_scope('total'):
                loss = tf.reduce_mean(diff)
                
                if regularize: 
                    print('Performing weight regularization using l2 loss')
                    sumloss=0
                    for w in weights:
                        sumloss += tf.nn.l2_loss(w)

                    l2_loss = lossPenalty*sumloss                
                    loss = tf.add(loss, l2_loss, name='loss')
                return loss           
            
#----------------------------------------------------------------------------------------------------------------
def compute_cross_entropy2(true_labels, prediction, deviceId="/gpu:0"):
    # This will not compute the mean unlike compute_cross_entropy    
    with tf.device(deviceId):  #"/gpu:0"
        with tf.name_scope('cross_entropyTest'):
            cross_entropy = tf.nn.softmax_cross_entropy_with_logits(labels=true_labels, logits=prediction)
            return cross_entropy

        
#----------------------------------------------------------------------------------------------------------------  
def optimizer(loss_function,eps,b1,b2,lr,mu,optimizer_type='adam', deviceId="/gpu:0"):
    with tf.device(deviceId):
        
        with tf.name_scope('optimize_n_train'):
            
            if optimizer_type.lower() == 'adam':
                print('Using ADAM optimizer')                                
                optimizer = tf.train.AdamOptimizer(learning_rate=lr,beta1=b1,beta2=b2,epsilon=eps)                
                grads = optimizer.compute_gradients(loss_function)
                train_step = optimizer.apply_gradients(grads)
                
            elif optimizer_type.lower() == 'gradientdescent':
                print('Using GSD optimizer')                
                optimizer = tf.train.GradientDescentOptimizer(learning_rate=lr)
                grads = optimizer.compute_gradients(loss_function)
                train_step = optimizer.apply_gradients(grads)
                
            elif optimizer_type.lower() == 'momentum':
                print('Using MOMENTUM optimizer')                
                optimizer = tf.train.MomentumOptimizer(learning_rate=lr, momentum=mu)
                grads = optimizer.compute_gradients(loss_function)
                train_step = optimizer.apply_gradients(grads)
                                
            return train_step, grads
        
#----------------------------------------------------------------------------------------------------------------  
def compute_accuracy(prediction, true_labels, deviceId="/gpu:0"):
    with tf.device(deviceId):
        with tf.name_scope('correct_prediction'):
            correct_prediction = tf.equal(tf.argmax(prediction,1), tf.argmax(true_labels, 1))   #### IS this correct ???
        with tf.name_scope('accuracy'):
            accuracy = tf.reduce_mean(tf.cast(correct_prediction, tf.float32))
            return accuracy                  
#----------------------------------------------------------------------------------------------------------------  
def makeDirectory(path):
    # Create directories for storing tensorflow events    
    if not os.path.exists(path):
        os.makedirs(path)
#----------------------------------------------------------------------------------------------------------------          
        
def train(architecture,fftSize,padding,trainSize,train_data, train_labels, val_data, val_labels, 
          activation,learning_rate,use_lr_decay,epsilon,b1,b2,mu,optimizer_type,
          drop1,drop2,drop3,model_path,log_dir, log_file, wDecayFlag,lossPenalty,
          applyBatchNorm, init_type='xavier',epochs=10, batch_size=32, num_classes=2,
          display_per_epoch=10,save_step = 1,summarize=True):
        
    print('Reset graph and create data and label placeholders..')
    tf.reset_default_graph()
    
    # test flag for batch norm
    tst = tf.placeholder(tf.bool)
    itr = tf.placeholder(tf.int32)
    
    # For Adam
    lr = tf.placeholder(tf.float32)
    eps= tf.placeholder(tf.float32)
    #beta1= tf.placeholder(tf.float32)
    #beta2= tf.placeholder(tf.float32)
    
    # For momentum
    momentum = tf.placeholder(tf.float32)

    if trainSize == '3sec':
        #input_data  = tf.placeholder(tf.float32, [None, 307500], name='x_input')
        input_data = tf.placeholder(tf.float32, [None, 300, 1025,1])  #make it 4d tensor        
        true_labels = tf.placeholder(tf.float32, [None, num_classes], name = 'y_input')
        
    elif trainSize == '4sec':
        #input_data  = tf.placeholder(tf.float32, [None, 410000], name='x_input')
        input_data = tf.placeholder(tf.float32, [None, 400, 1025,1])  #make it 4d tensor        
        true_labels = tf.placeholder(tf.float32, [None, num_classes], name = 'y_input')
        
    elif trainSize == '5sec':
        #input_data  = tf.placeholder(tf.float32, [None, 512500], name='x_input')
        input_data = tf.placeholder(tf.float32, [None, 500, 1025,1])  #make it 4d tensor
        true_labels = tf.placeholder(tf.float32, [None, num_classes], name = 'y_input')
        
    elif trainSize == '1sec':
        #input_data  = tf.placeholder(tf.float32, [None, 512500], name='x_input')
        if fftSize == 512:
            input_data = tf.placeholder(tf.float32, [None, 100, 257,1]) # We use 512 fft
            true_labels = tf.placeholder(tf.float32, [None, num_classes], name = 'y_input')
        elif fftSize == 256:
            input_data = tf.placeholder(tf.float32, [None, 100, 129,1])
            true_labels = tf.placeholder(tf.float32, [None, num_classes], name = 'y_input')        

    # Placeholders for droput probability
    keep_prob1 = tf.placeholder(tf.float32)
    keep_prob2 = tf.placeholder(tf.float32)
    keep_prob3 = tf.placeholder(tf.float32)
    
    if activation == 'relu':
        act = tf.nn.relu
    elif activation == 'elu':
        act = tf.nn.elu
    elif activation == 'crelu':
        act = tf.nn.crelu
    elif activation == 'mfm':
        act = 'mfm'
        
    update_ema = None
    model_prediction=None
    network_weights=None
    activations=None
    biases=None
    
    dataType = 'train'   ### Take care of this later

    if applyBatchNorm:
        _, model_prediction, network_weights, update_ema, tst, itr = cnnModel0_BN(
            input_data, act, init_type, keep_prob1, keep_prob2, tst, itr)
    else:         
        if architecture == 1:           
            _, model_prediction,network_weights,activations,biases= nn_architecture.cnnModel1(dataType,trainSize, input_data, act,init_type,num_classes,fftSize,padding,keep_prob1,keep_prob2,keep_prob3)
        elif architecture == 2:
            _, model_prediction,network_weights,activations,biases= nn_b.cnnModel1(trainSize,input_data, act,init_type,num_classes,fftSize,padding,keep_prob1,keep_prob2,keep_prob3)
        elif architecture == 3:
            _, model_prediction,network_weights,activations,biases= nn_b.cnnModel2(trainSize,input_data, act,init_type,num_classes,fftSize,padding,keep_prob1,keep_prob2,keep_prob3)
        elif architecture == 5:
            _, model_prediction,network_weights,activations,biases= nn_r.cnnModel5(trainSize,input_data, act,init_type,num_classes,fftSize,padding,keep_prob1,keep_prob2,keep_prob3)

            
    cross_entropy = compute_cross_entropy(true_labels, model_prediction, network_weights, wDecayFlag, lossPenalty)    
    tf.summary.scalar('cross_entropy', cross_entropy)
    
    # Loss function to use during testing
    cross_entropy2 = compute_cross_entropy2(true_labels, model_prediction)
    
    # Training function that includes optimization       
    train_step,grads = optimizer(cross_entropy,eps,b1,b2,lr,mu,optimizer_type)
    
    # Compute accuracy ocassionaly
    accuracy = compute_accuracy(model_prediction, true_labels)
    tf.summary.scalar('accuracy', accuracy)
   
    # Merge all the summaries into single one
    merged_summary = tf.summary.merge_all()
                
    print('Create session and launch graph..')
    sess = tf.Session(config=tf.ConfigProto(allow_soft_placement=True))               
    init = tf.global_variables_initializer()       
    sess.run(init)
    print('Graph launched successfully..')
    
    # create a saver instance to restore model. Just keep the best model
    saver = tf.train.Saver(max_to_keep=1)       
    
    # Create directories for writing summaries
    #if os.path.exists(log_dir):
    #    shutil.rmtree(log_dir)  
        
    makeDirectory(log_dir+'/train')
    makeDirectory(log_dir+'/test')        
    logfile = open(log_file, 'w')
               
    # Create FileWriter for training and test logs
    train_writer = tf.summary.FileWriter(log_dir + '/train', sess.graph)
    test_writer = tf.summary.FileWriter(log_dir + '/test')
                
    total_batches = int(len(train_data)/batch_size)   #+1
    val_total_batches = int(len(val_data)/batch_size) #+1
    print('Total_batches on training set = ', total_batches)
    print('Total_batches on validation set = ', val_total_batches)
    
    n=0
    m=0
    display_step = max(int(round(float(total_batches)/display_per_epoch)),1)
       
    logfile.write('Starting CNN model training : '+str(datetime.now())+'\n')                
    print('Starting CNN model training at : '+str(datetime.now()))
    print('Display step is ', display_step)
    
    #Store CE train, val loss in a list
    train_ce_loss = list()
    val_ce_loss = list()    
    train_accuracy = list()
    val_accuracy = list()    
    best_validation_accuracy=0
    previous_training_accuracy=0
    best_validation_loss=999
    previous_training_loss=999
    loss_tracker = 0
    loop_stopper =0
    
    # Main training loop
    i=0
    
    ## Learning rate decay
    max_learning_rate = 0.003
    min_learning_rate = 0.0001
    decay_speed = 2000
    
    #dataLogfile = open('datalog.txt', 'w')
            
    for epoch in range(epochs):     
        print("Epoch: ", epoch+1)
        # Now prepare training data generator to iterate over mini-batches and run training loop
        batch_generator = dataset.iterate_minibatches(train_data, train_labels, batch_size, shuffle=True)
                                
        #learning_rate=new_lr                      
        print('Learning rate used in Epoch '+ str(epoch) + ' is = ' + str(learning_rate))     
        
        for j in range(total_batches):            
            data, labels = next(batch_generator)                        
            data = dataset.reshape_minibatch(data)
            print('Input data 0 shape is: ',data[0].shape) 
            
            # Run the training optimization step on mini-batch
            sess.run(train_step, feed_dict={input_data:data, true_labels:labels,keep_prob1:drop1, 
                                            keep_prob2:drop2,keep_prob3:drop3,tst:False,itr:i,eps:epsilon,lr:learning_rate})
            
            print('Optimization finished using batch:',j+1)
            
            # Check the weights in the first conv layer
            #w = sess.run(network_weights)            
            
            ### Display some stats to track unwanted behaviour
            #-------------------------------------------------------------------------------
            print('\n^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^')
            rawPrediction_post= sess.run(model_prediction,feed_dict={input_data:data, 
                                        true_labels:labels,keep_prob1:1.0,keep_prob2:1.0, keep_prob3:1.0,tst:False, itr:i})            
            
            #print('\n Printing first 15 Scores/Prediction (WX+B): \n', rawPrediction_post[0:15])            
            loss2=sess.run(cross_entropy2, feed_dict={input_data:data, true_labels:labels, keep_prob1: 1.0, 
                                                keep_prob2: 1.0, keep_prob3:1.0, tst:False, itr:i})
            
            #print('Shape of weights in first conv layer:', w[0].shape) #(3, 257, 1, 128)
            #print('Printing few weigths of the first conv layer', w[0][0][0][0:20])
            print('\nPrinting the CE loss of every samples in this batch \n', loss2)
            print('\nAvg batch CE loss = ', sess.run(tf.reduce_mean(loss2)))
            print('\n^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n')
            #-------------------------------------------------------------------------------
            
            #------------------------
            # added for batch norm
            if applyBatchNorm:
                sess.run(update_ema, {input_data: data, true_labels: labels, tst: False, 
                                      itr:i,keep_prob1:1.0,keep_prob2:1.0, keep_prob3:1.0,})
                i+=1
            #------------------------
            
            # Occasionally write training summaries. Enable this to view stuffs in TensorBoard !
            #if j%display_step==0:                                                
            #    batch_summary = sess.run(
            #        merged_summary,feed_dict={input_data: data, true_labels: labels,
            #                                  keep_prob1: 1.0, keep_prob2: 1.0, keep_prob3:1.0,tst:False, itr:i})
            #    train_writer.add_summary(batch_summary,global_step=m)
            #    m+=1                                                             
        
        '''
        # Write the summary using Validation data
        print("Finished Epoch: ", epoch+1)
        print('\n writing summaries for validation data now ..')
        test_batch_generator = dataset.iterate_minibatches(val_data, val_labels, batch_size, shuffle=True)
        for k in range(val_total_batches):
            data, labels = next(test_batch_generator)
            data, labels = dataset.reshape_minibatch(data, labels)
                        
            # Occasionally write training summaries
            if k%display_step==0:                                                
                batch_summary = sess.run(
                    merged_summary, feed_dict={input_data: data, 
                                               true_labels: labels,keep_prob1:1.0, keep_prob2:1.0, tst:False, itr:i})
                test_writer.add_summary(batch_summary,global_step=n)
                n+=1
         '''  
        
        '''
        # After each training epoch, exponentially decay learning rate
        # Using Exponential decay learning rate
        if use_lr_decay:
            #learning_rate = min_learning_rate + (max_learning_rate - min_learning_rate) * math.exp(-i/decay_speed)
            learning_rate=learning_rate * decay
        '''    
        
        avg_loss=0
        avg_acc=0                
        #print('Testing performance on training set now ..')
        # Now after each epoch we test performance on entire training set and validation set.        
        #train_batch_generator = dataset.iterate_minibatches(train_data, train_labels, batch_size, shuffle=False)        
        #avg_loss, avg_acc = testonValidationData(sess,train_batch_generator, total_batches,input_data,true_labels,
        #                                         keep_prob1, keep_prob2,keep_prob3,tst,itr, cross_entropy2,accuracy)
                                 
        # Test on Validation data using model trained        
        # we keep shuffle =False because we are testing, so no need to shuffle
        print('Testing performance on validation set now ..')
        test_batch_generator = dataset.iterate_minibatches(val_data, val_labels, batch_size, shuffle=False)
        val_loss, val_acc = testonValidationData(sess, test_batch_generator,val_total_batches, input_data, true_labels,
                                    keep_prob1, keep_prob2, keep_prob3, tst,itr, cross_entropy2, accuracy)
        
        # Append to the list
        train_ce_loss.append(avg_loss)
        train_accuracy.append(avg_acc)
        val_ce_loss.append(val_loss)
        val_accuracy.append(val_acc)         
                
        # Write to output file                
        logfile.write('-------------------------------------------------------'+'\n')
        #logfile.write("Epoch " +str(epoch)+", training Avg CE loss = "+"{:.5f}".format(avg_loss)+'\n')       
        logfile.write("Avg CE loss on Validation data = "+"{:.5f}".format(val_loss)+'\n')
        #logfile.write("Avg Accuracy on training data = "+"{:.5f}".format(avg_acc)+'\n')
        logfile.write("Avg Accuracy on Validation data = "+"{:.5f}".format(val_acc)+'\n')
        
        # Display on screen
        #print("Avg CE loss on Training data = "+"{:.5f}".format(avg_loss))
        print("Avg CE loss on Validation data = "+"{:.5f}".format(val_loss))
        #print("Avg Accuracy on training data = "+"{:.5f}".format(avg_acc))
        print("Avg Accuracy on Validation data = "+"{:.5f}".format(val_acc))
        print('-------------------------------------------------------'+'\n')
        
        # Save the model only if it give better accuracy on validation set and shows different training
        # accuracy that previous epoch !!
        # Note that once model starts overfitting the accuracy will not change.
        
        if val_loss < best_validation_loss:    # and avg_acc != previous_training_accuracy:
            
            # Reset the loss_tracker
            loss_tracker = 0
            
            print('Avg validation accuracy improved than before. Saving this model now !')             
            best_validation_accuracy = val_acc
            best_validation_loss = val_loss
            #saved = saver.save(sess, os.path.join(model_path,"bestModel.ckpt"),global_step=epoch+1)
            saved = saver.save(sess, os.path.join(model_path,"bestModel.ckpt"))
            logfile.write('******************************************************'+'\n\n')
            logfile.write("Epoch " +str(epoch)+", model is best so far. We save it.." + '\n')
                        
            print('Also we compute Training loss of this best Model for records !!')
            train_batch_generator = dataset.iterate_minibatches(train_data, train_labels, batch_size, shuffle=False)
            avg_loss, avg_acc = testonValidationData(sess,train_batch_generator, total_batches,input_data,true_labels,
                                                    keep_prob1, keep_prob2,keep_prob3,tst,itr, cross_entropy2,accuracy)
            
            print("Avg CE loss on Training data = "+"{:.5f}".format(avg_loss))
            print("Avg Accuracy on training data = "+"{:.5f}".format(avg_acc))
            
            logfile.write("The Epoch " +str(epoch)+", has training Avg CE loss = "+"{:.5f}".format(avg_loss)+'\n')
            logfile.write('******************************************************'+'\n\n')

            
        else:
            # The loss_tracker keeps track of whether there has been any improvement in validation loss
            # over last N epochs. If not stop training loop !! Early stopping !            
            loss_tracker += 1
                        
        
        # We decrease the learning rate if no progress on validation loss over the last 5 epochs
        '''if loss_tracker > 4:
            print('Validation loss did not improve over last 5 Epochs. We decrease Learning Rate !')
            logfile.write("...... Learning rate is now decreased..." + '\n')
            learning_rate=learning_rate / 2
            loop_stopper += loss_tracker
            loss_tracker=0 '''
            

        # We reduce learning rate only three times
        if loss_tracker > 50 and val_loss > best_validation_loss:
            print('Validation loss did not improve in last 50 epochs. We abort training loop.')
            logfile.write("Validation loss did not improve over last 50 Epochs. We abort training loop..." + '\n')
            break
        #else:
        #    loop_stopper=0
            
    logfile.write('Optimization finished at : '+str(datetime.now())+'\n')
    print('Training optimization is finished: '+str(datetime.now()))
                
    #Closing the log stats file
    logfile.close()
        
    ######## Here run feature extraction and prediction using the trained model ##############
    # Save the score and features for each train,dev,eval inside the same trained model folder
    # This avoids confusion later on
    
    normalise=True          # will always be true, so no need to pass         
    normType = 'global'      # not passed to model.py, but mostly we do global
    print('MAKE SURE THAT NORMALIZATION IS DONE CORRECTLY ON TEST SETS !!')
    
    #TODO
    # Create a unified pipeline that will train model and perform testing in a single go
    # Make model.py recieve train, dev and eval data with some other missing parameters.
        
    specType='mag_spec'    # This is not passed to model.py ! need to see !
    duration=1   # need to change like i did in feature_extraction.py
        
    '''
    architecture = 2
    targets=num_classes
    fftSize=256
    padding=True    
    init_type='xavier'
    activation='elu'
    '''                  # these are passed to model.py
        
    '''
    featType=['scores','bottleneck']
    
    batch_size=100  #during Testing
    extractor.get_scores_and_features(model_path,batch_size,init_type,activation,normType,normalise,architecture,specType,
                                  targets,fftSize,duration,padding,featType)
    '''
    ###########################################################################################
    
    return train_ce_loss, val_ce_loss, train_accuracy, val_accuracy


def testonValidationData(sess, test_batch_generator, total_batches,input_data, true_labels,
                         keep_prob1,keep_prob2,keep_prob3,tst,itr,cross_entropy, accuracy):
    
    loss = list()
    acc = list()
    
    for k in range(total_batches):
        data, labels = next(test_batch_generator)
        data = dataset.reshape_minibatch(data) #, labels)
        batch_loss, batch_acc = sess.run([cross_entropy, accuracy], 
                                         feed_dict={input_data: data, true_labels: labels,
                                                    keep_prob1: 1.0, keep_prob2: 1.0,  keep_prob3: 1.0, tst:True, itr:k})
        loss.append(batch_loss)
        acc.append(batch_acc)
            
    return np.mean(loss), np.mean(acc)