#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
 Main function that calls module to train a Convolutional Neural Network
 for detecting between replayed and genuine speech.
'''

# Load standard modules
from __future__ import print_function
import sys
import os
import io
import numpy as np

from optparse import OptionParser
from plotGraph import plot_entropy_loss
from plotGraph import plot_2dGraph
from utility import makeDirectory
from dataset import load_data
from dataset import compute_global_norm

# Load userdefined modules
import audio
import dataset
import model
  
def trainCNN_on_handcrafted_features():

    #CNN Training parameters
    activation = 'mfm'  #choose activation: mfm,elu, relu, mfsoftmax, tanh ?
    init_type='xavier'  #'truncated_normal' #'xavier'  #or 'truncated_normal'

    batch_size = 32
    epochs = 200     #500      
    
    # Regularizer parameters    
    wDecayFlag = False         #whether to perform L2 weight decay or not
    lossPenalty = 0.001       # Using lambda=0.001 .
    applyBatchNorm = False    
    deviceId = "/gpu:0"  
      
    # Adam parameters
    optimizer_type = 'adam'
    b1=0.9
    b2=0.999
    epsilon=0.1
    momentum=0.95 #0.95
    dropout1=0.5  #0.3                  #for input to first FC layer
    dropout2=0.5  #0.3                  #for intermediate layer input    
    drops=[0.5]                   # 50% dropout the inputs of FC layers
    lambdas = [0.0005, 0.001]
    targets=2
    
    architectures = [1]
    trainingSize = [1]   #in seconds
    
    use_lr_decay=True
    learning_rates=[0.0022, 0.0008, 0.005, 0.0004]
    #learning_rates=np.random.uniform(0.003,0.0005,10)    #Take randomly drawn lr from uniform distribution between 0.001-0.0001
    #learning_rates=np.random.uniform(0.01,0.0001,10)
    
    # Note: LR =0.01 explodes badly. We get the huge cross entropy values we used to get before.
                                      
    #inputTypes=['CQCC','LFCC','LPCC','MFCC','RFCC']  #'IMFCC'    # i ran this in 1 kapoor   

    #inputTypes=['IMFCC', 'SCMC']   # this was running on kapoor 0
    inputTypes=['RFCC','LFCC','SCMC','IMFCC']   # this is running on kapoor 1   

    padding=True
    
    augment = True 
    trainPercentage=1.0    #Each training epoch will see only 50% of the original data at random !
    valPercentage=1.0   
            
    if augment:        
        spectrogramPath='/homes/bc305/myphd/stage2/deeplearning.experiment1/features_1sec_shift/'
    else:
        spectrogramPath='/homes/bc305/myphd/stage2/deeplearning.experiment1/features/'        
            
    # Used following paths since I moved the scripts in git and used link so that code are synchronised
    tensorboardPath = '/homes/bc305/myphd/stage2/deeplearning.experiment1/CNN3/tensorflow_log_dir/'
    modelPath = '/homes/bc305/myphd/stage2/deeplearning.experiment1/CNN3/models_augmented/'
                    
    duration=1
    fftSize=512
    
    for specType in inputTypes:
                                      
        outPath = spectrogramPath +specType + '/'
        mean_std_file = outPath+'train/mean_std.npz'
                
        # Load training data, labels and perform norm
        tD,tL = dataset.load_data(outPath+'train/')
        tL = dataset.get_labels_according_to_targets(tL, targets)
        
        assert(len(tD)==len(tL))
        
        if not os.path.exists(mean_std_file):
            print('Computing Mean_std file ..')
            dataset.compute_global_norm(tD,mean_std_file)
            
        # We will try utterance based norm later   
        #tD = dataset.normalise_data(tD,mean_std_file,'utterance')    # utterance level      
        tD = dataset.normalise_data(tD,mean_std_file,'global_mv')    # global
                        
        # Now take only 80% of the new augmented data to use for validation
        # Just to save some time during training
        #devD,devL = dataset.get_random_data(outPath+'dev/',batch_size,valPercentage)
        devD,devL = dataset.load_data(outPath+'dev/')
        devL = dataset.get_labels_according_to_targets(devL, targets)
        assert(len(devD)==len(devL))                                
                        
        #devD = dataset.normalise_data(devD,mean_std_file,'utterance')
        devD = dataset.normalise_data(devD,mean_std_file,'global_mv')                                
                
        ### We are training on TRAIN set and validating on DEV set        
        t_data = tD
        t_labels = tL
        v_data = devD
        v_labels = devL                
        
        print('Training model on ', specType)

        for dropout in drops:                  # Just dropout 1.0 and 0.5 to all inputs of DNN
            architecture = architectures[0]
            penalty=0.001
            
            for lr in learning_rates:                                               
                                
                hyp_str='keep_'+str(dropout1)+'_'+str(dropout2)+'_'+str(dropout)+'_'+str(specType)+'_lr_'+str(lr)

                print('Hyper-parameter string is: ', hyp_str) 
                
                log_dir = tensorboardPath+ '/model1_120max_handcrafted_with_0.85Decay/'+ str(specType) + 'drops'+'/'+ hyp_str
                model_save_path = modelPath + '/model1_120max_handcrafted_with_0.85Decay/'+ str(specType) +'drops'+'/'+ hyp_str
                logfile = model_save_path+'/training.log'
                
                figDirectory = model_save_path        
                makeDirectory(model_save_path)
                                                
                tLoss,vLoss,tAcc,vAcc=model.train(specType,architecture,fftSize,padding,duration,t_data,t_labels,
                                                  v_data,v_labels,activation,lr,use_lr_decay,epsilon,b1,b2,momentum,
                                                  optimizer_type,dropout1,dropout2,dropout,model_save_path,log_dir,
                                                  logfile,wDecayFlag,penalty,applyBatchNorm,init_type,epochs,batch_size,
                                                  targets,augment)#,trainPercentage,valPercentage)                                                                                                                                        
                #plot_2dGraph('#Epochs', 'Avg CE Loss', tLoss,vLoss,'train_ce','val_ce', figDirectory+'/loss.png')
                #plot_2dGraph('#Epochs', 'Avg accuracy', tAcc,vAcc,'train_acc','val_acc',figDirectory+'/acc.png')
                #plot_2dGraph('#Epochs', 'Val loss and accuracy', vLoss,vAcc,'val_loss','val_acc',figDirectory+'/v_ls_acc.png')   
                        

trainCNN_on_handcrafted_features()
