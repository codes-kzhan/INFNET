import numpy as np
import theano
from theano import tensor as T
import lasagne
import random as random
import pickle
import cPickle
import time
import sys
from lasagne_embedding_layer_2 import lasagne_embedding_layer_2
from random import randint
from crf import CRFLayer
from crf_utils import crf_loss0, crf_accuracy0

random.seed(1)
np.random.seed(1)
eps = 0.0000001

def saveParams(para, fname):
        f = file(fname, 'wb')
        cPickle.dump(para, f, protocol=cPickle.HIGHEST_PROTOCOL)
        f.close()

def get_minibatches_idx(n, minibatch_size, shuffle=False):
        idx_list = np.arange(n, dtype="int32")

        if shuffle:
            np.random.shuffle(idx_list)

        minibatches = []
        minibatch_start = 0
        for i in range(n // minibatch_size):
            minibatches.append(idx_list[minibatch_start:
                                    minibatch_start + minibatch_size])
            minibatch_start += minibatch_size

        if (minibatch_start != n):
            # Make a minibatch out of what is left
            minibatches.append(idx_list[minibatch_start:])

        return zip(range(len(minibatches)), minibatches)

class CRF_model(object):

        def prepare_data(self, seqs, labels):
                lengths = [len(s) for s in seqs]
                n_samples = len(seqs)
                maxlen = np.max(lengths)

                x = np.zeros((n_samples, maxlen)).astype('int32')
                x_mask = np.zeros((n_samples, maxlen)).astype(theano.config.floatX)
                x_mask1 = np.zeros((n_samples, maxlen)).astype(theano.config.floatX)
                y = np.zeros((n_samples, maxlen)).astype('int32')
                for idx, s in enumerate(seqs):
                        x[idx,:lengths[idx]] = s
                        x_mask[idx,:lengths[idx]] = 1.
                        y[idx,:lengths[idx]] = labels[idx]
                        x_mask1[idx,lengths[idx]-1] = 1.
                return x, x_mask, x_mask1, y, maxlen
        

        def __init__(self,  We_initial, params):
                self.textfile = open(params.outfile, 'w')
                We = theano.shared(We_initial)
                embsize = We_initial.shape[1]
                hidden = params.hidden
                start0 =  np.random.uniform(-0.02, 0.02, (1, 25)).astype('float32')
                end0 =  np.random.uniform(-0.02, 0.02, (1, 25)).astype('float32')
                start = theano.shared(start0)
                end = theano.shared(end0)		

                input_var = T.imatrix(name='inputs')
                target_var = T.imatrix(name='targets')
                mask_var = T.fmatrix(name='masks')
                mask_var1 = T.fmatrix(name='masks1')
                length = T.iscalar()
		
                Wyy0 = np.random.uniform(-0.02, 0.02, (26, 26)).astype('float32')
                Wyy = theano.shared(Wyy0)
                
                l_in_word = lasagne.layers.InputLayer((None, None))
                l_mask_word = lasagne.layers.InputLayer(shape=(None, None))

     	        if params.emb ==1:
                        l_emb_word = lasagne.layers.EmbeddingLayer(l_in_word,  input_size= We_initial.shape[0] , output_size = embsize, W =We)
                else:
                        l_emb_word = lasagne_embedding_layer_2(l_in_word, embsize, We)

                l_lstm_wordf = lasagne.layers.LSTMLayer(l_emb_word, hidden, mask_input=l_mask_word)
                l_lstm_wordb = lasagne.layers.LSTMLayer(l_emb_word, hidden, mask_input=l_mask_word, backwards = True)
                concat = lasagne.layers.concat([l_lstm_wordf, l_lstm_wordb], axis=2)
                l_reshape_concat = lasagne.layers.ReshapeLayer(concat,(-1,2*hidden))
                l_local = lasagne.layers.DenseLayer(l_reshape_concat, num_units= 25, nonlinearity=lasagne.nonlinearities.linear)

                network_params = lasagne.layers.get_all_params(l_local, trainable=True)
                network_params.append(Wyy)

                f = open('LF_LIFU_Simple_CRF_lstm_pretrain.Batchsize_10_dropout_0_LearningRate_0.1_1e-050_emb_0.pickle','r')
                data = pickle.load(f)
                f.close()

                for idx, p in enumerate(network_params):
                        p.set_value(data[idx])

                l_in_word_a = lasagne.layers.InputLayer((None, None))
                l_mask_word_a = lasagne.layers.InputLayer(shape=(None, None))
                l_emb_word_a = lasagne_embedding_layer_2(l_in_word_a, embsize, We)
                if params.dropout:
                        l_emb_word_a = lasagne.layers.DropoutLayer(l_emb_word_a, p=0.5)
                l_lstm_wordf_a = lasagne.layers.LSTMLayer(l_emb_word_a, hidden, mask_input=l_mask_word_a)
                l_lstm_wordb_a = lasagne.layers.LSTMLayer(l_emb_word_a, hidden, mask_input=l_mask_word_a, backwards = True)
                l_reshapef_a = lasagne.layers.ReshapeLayer(l_lstm_wordf_a ,(-1, hidden))
                l_reshapeb_a = lasagne.layers.ReshapeLayer(l_lstm_wordb_a ,(-1,hidden))
                concat2_a = lasagne.layers.ConcatLayer([l_reshapef_a, l_reshapeb_a])
                l_local_a = lasagne.layers.DenseLayer(concat2_a, num_units= 25, nonlinearity=lasagne.nonlinearities.softmax)
                a_params = lasagne.layers.get_all_params(l_local_a, trainable=True)
                self.a_params = a_params

                def inner_function( targets_one_step, mask_one_step,  prev_label, tg_energy):
                        """
                        :param targets_one_step: [batch_size, t]
                        :param prev_label: [batch_size, t]
                        :param tg_energy: [batch_size]
                        :return:
                        """                 
                        new_ta_energy = T.dot(prev_label, Wyy[:-1,:-1])
                        new_ta_energy_t = tg_energy + T.sum(new_ta_energy*targets_one_step, axis =1)
                        tg_energy_t = T.switch(mask_one_step, new_ta_energy_t,  tg_energy)
                        return [targets_one_step, tg_energy_t]

                local_energy = lasagne.layers.get_output(l_local, {l_in_word: input_var, l_mask_word: mask_var})
                local_energy = local_energy.reshape((-1, length, 25))
                local_energy = local_energy*mask_var[:,:,None]
                #####################
                # for the end symbole of a sequence
                ####################
                end_term = Wyy[:-1,-1]
                local_energy = local_energy + end_term.dimshuffle('x', 'x', 0)*mask_var1[:,:, None]

                predy0 = lasagne.layers.get_output(l_local_a, {l_in_word_a:input_var, l_mask_word_a:mask_var})
                predy_in = T.argmax(predy0, axis=1)
                A = T.extra_ops.to_one_hot(predy_in, 25)
                A = A.reshape((-1, length, 25))		
                predy = predy0.reshape((-1, length, 25))
                predy = predy*mask_var[:,:,None]

                targets_shuffled = predy.dimshuffle(1, 0, 2)
                target_time0 = targets_shuffled[0]
                masks_shuffled = mask_var.dimshuffle(1, 0)		 
                initial_energy0 = T.dot(target_time0, Wyy[-1,:-1])

                initials = [target_time0, initial_energy0]
                [ _, target_energies], _ = theano.scan(fn=inner_function, outputs_info=initials, sequences=[targets_shuffled[1:], masks_shuffled[1:]])
                cost11 = target_energies[-1] + T.sum(T.sum(local_energy*predy, axis=2)*mask_var, axis=1)


                targets_shuffled0 = A.dimshuffle(1, 0, 2)
                target_time00 = targets_shuffled0[0]

                initial_energy00 = T.dot(target_time00, Wyy[-1,:-1])
                initials0 = [target_time00, initial_energy00]
                [ _, target_energies0], _ = theano.scan(fn=inner_function, outputs_info=initials0, sequences=[targets_shuffled0[1:], masks_shuffled[1:]])
                cost110 = target_energies0[-1] + T.sum(T.sum(local_energy*A, axis=2)*mask_var, axis=1)	
                predy_f =  predy.reshape((-1, 25))
                y_f = target_var.flatten()

                ce_hinge = lasagne.objectives.categorical_crossentropy(predy_f, y_f)
                ce_hinge = ce_hinge.reshape((-1, length))
                ce_hinge = T.sum(ce_hinge* mask_var, axis=1)/mask_var.sum(axis=1)
                
                entropy_term = - T.sum(predy_f * T.log(predy_f + eps), axis=1)
                entropy_term = entropy_term.reshape((-1, length))
                entropy_term = T.sum(entropy_term*mask_var, axis=1)
                """
                label sequence language model score for each sequence
                """
                l_LM_in = lasagne.layers.InputLayer((None, None, 25))
                l_LM_mask = lasagne.layers.InputLayer(shape=(None, None))
                l_LM_lstm = lasagne.layers.LSTMLayer(l_LM_in, hidden, mask_input=l_LM_mask)
                l_reshape_LM = lasagne.layers.ReshapeLayer(l_LM_lstm,(-1,hidden))
                l_LM = lasagne.layers.DenseLayer(l_reshape_LM, num_units= 26, nonlinearity=lasagne.nonlinearities.softmax)		
                LM_params = lasagne.layers.get_all_params(l_LM, trainable=True)
                LM_params.append(start)
                LM_params.append(end)
                f = open('Label_LM.pickle','r')
                data = pickle.load(f)
                f.close()
                for idx, p in enumerate(LM_params):
                        p.set_value(data[idx])
		

                predy_tmp = predy[:,0, :].reshape((-1, 1, 25))
                tmp = T.ones_like(predy_tmp)
                sos = tmp*(start.dimshuffle('x', 0, 1))
                eos = tmp*(end.dimshuffle('x', 0, 1))
                y_lm_in = T.concatenate([sos, predy], axis=1)
                y_lm_out = T.concatenate([predy, eos], axis=1)	
                lm_mask_var = T.concatenate([tmp[:,0, 0].reshape((-1,1)), mask_var], axis=1)
                LM_out = lasagne.layers.get_output(l_LM, {l_LM_in:y_lm_in, l_LM_mask:lm_mask_var})
                LM_out = LM_out.reshape((-1, length+1, 26))			
                LM_cost = T.sum(T.log(T.sum(LM_out[:,:-1,:-1]*y_lm_out[:,:-1,:], axis=2)+ eps)*mask_var, axis=1)
                cost = T.mean(-cost11) -  params.l3* T.mean(entropy_term) - params.lm*T.mean(LM_cost)

                updates_a = lasagne.updates.sgd(cost, a_params, params.eta)
                updates_a = lasagne.updates.apply_momentum(updates_a, a_params, momentum=0.9)
                self.train_fn = theano.function([input_var, target_var, mask_var, mask_var1, length], [cost, T.mean(entropy_term), T.mean(LM_cost)], updates = updates_a, on_unused_input='ignore')

                prediction = T.argmax(predy, axis=2)
                corr = T.eq(prediction, target_var)
                corr_train = (corr * mask_var).sum(dtype=theano.config.floatX)
                num_tokens = mask_var.sum(dtype=theano.config.floatX)
        	
                self.eval_fn = theano.function([input_var, target_var, mask_var, mask_var1, length], [cost11, cost110, corr_train, num_tokens, prediction], on_unused_input='ignore')

		
        def train(self, trainX, trainY, devX, devY, testX, testY, params):	
		
                devx0, devx0mask, devx0mask1, devy0, devmaxlen = self.prepare_data(devX, devY)
                testx0, testx0mask, testx0mask1, testy0, testmaxlen = self.prepare_data(testX, testY)
                start_time = time.time()
                bestdev = -1
                bestdev_time =0
                counter = 0
                try:
            	        for eidx in xrange(100):
                                n_samples = 0
                                start_time1 = time.time()
                                kf = get_minibatches_idx(len(trainX), params.batchsize, shuffle=True)
                                uidx = 0
                                aa = 0
                                bb = 0
                                for _, train_index in kf:
                                        uidx += 1
                                        x0 = [trainX[ii] for ii in train_index]
                                        y0 = [trainY[ii] for ii in train_index]
                                        n_samples += len(train_index)
                                        x0, x0mask, x0mask1, y0, maxlen = self.prepare_data(x0, y0)
                                        cost, entropy, lm = self.train_fn(x0, y0, x0mask, x0mask1, maxlen)
								
				
                                self.textfile.write("Seen samples:%d   \n" %( n_samples)  )
                                self.textfile.flush()
                                end_time1 = time.time()
                                bestdev0 = 0
                                best_t0 = 0
                                bestdev0_0 = 0
                                best_t1 = 0

                                start_time2 = time.time()				
                                devloss, devloss0, devpred, devnum, dev_pred   = self.eval_fn(devx0, devy0, devx0mask, devx0mask1, devmaxlen)
                                testloss, _, testpred, testnum, _ = self.eval_fn(testx0, testy0, testx0mask, testx0mask1, testmaxlen)
                                devacc = 1.0*devpred/devnum
                                testacc = 1.0*testpred/testnum	
                                devlength = [len(s) for s in devX]			
                                print  'devacc ', devacc, 'testacc ', testacc		
                                end_time2 = time.time()
                                if bestdev < devacc:
                                        bestdev = devacc
                                        best_t = eidx
                                   				
                                self.textfile.write("epoches %d  devacc %f  testacc %f trainig time %f test time %f \n" %( eidx + 1, devacc, testacc, end_time1 - start_time1, end_time2 - start_time2 ) )
                                self.textfile.flush()       
                except KeyboardInterrupt:
                        self.textfile.write( 'classifer training interrupt \n')
                        self.textfile.flush()
                end_time = time.time()		
                self.textfile.write("best dev acc: %f  at time %d \n" % (bestdev, best_t))
                print 'bestdev ', bestdev, 'at time ',best_t
                self.textfile.close()
		
