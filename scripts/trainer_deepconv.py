import os
import glob
import torch
import shutil
import argparse
import datetime
import itertools
import numpy as np
from   tqdm import tqdm
from   PIL import Image
from   skimage import io, transform

import torch.nn.functional as F
from   torchvision.utils import save_image
from   torchvision import transforms, datasets

from model.VGG_midout import VGG16_mid
from model.EDnew import Encoder, Decoder
from scripts.trainer_base import Trainer_Base

from components.reporter import Reporter
from components.utils import gram_matrix_cxh
from components.transformer_conv import Transformer
from components.data_loader_styletransfer_conditional import GetLoader,denorm

class Trainer(Trainer_Base):

    def create_model(self):
        self.encoder = Encoder(self.config.channels).cuda()
        self.decoder = Decoder(self.config.channels).cuda()
        self.D = VGG16_mid().cuda()
        self.attention1 = Transformer(4,self.config.channels*8,self.config.topk,True,False).cuda()

    def train(self):
        self.create_model()
        losses      = {'perceptual':[], 'content':[]}
        optimizer   = torch.optim.Adam(itertools.chain( self.attention1.parameters(), 
                                        self.encoder.parameters(), 
                                        self.decoder.parameters()), 
                                        lr=self.config.learning_rate)
        
        # criterion   = torch.nn.L2Loss()
        # self.criterion = torch.nn.MSELoss(reduction='mean')

        

        total_loader  = GetLoader(self.config.style_dir, self.config.content_dir,
                            self.config.selected_style_dir, self.config.selected_content_dir,
                            self.config.image_size, self.config.batch_size, self.config.workers)
        
        data_len = len(total_loader)
        iter_epoch = data_len // self.config.batch_size

        self.D.eval()
        self.encoder.train()
        self.decoder.train()
        self.attention1.train()
        self.reporter.writeInfo("Start to train the model")

        for num_epoch in range(self.config.total_epoch):
            for num_iter in range(iter_epoch):

                content, style, _ = total_loader.next()

                content = content.cuda()
                style   = style.cuda()

                fea_c   = self.encoder(content)
                fea_s   = self.encoder(style)
                
                out_feature, attention_map = self.attention1(fea_c, fea_s)
                out_content     = self.decoder(out_feature)
                
                # _, _, c3, _     = self.D(content)
                h1, h2, h3, h4  = self.D(out_content)
                s1, s2, s3, s4  = self.D(style)

                # loss_content= self.criterion(c3,h3)
                loss_content= self.criterion(out_content,content)
                loss_style  = 0
                # for t in range(4):
                loss_style = self.criterion(gram_matrix_cxh(s1), gram_matrix_cxh(h1)) + \
                        self.criterion(gram_matrix_cxh(s2), gram_matrix_cxh(h2)) + \
                        self.criterion(gram_matrix_cxh(s3), gram_matrix_cxh(h3)) + \
                        self.criterion(gram_matrix_cxh(s4), gram_matrix_cxh(h4))

                loss = loss_content*self.config.content_weight + loss_style*self.config.style_weight

                if num_iter%200 == 0:
                    print(
                        "Epoch[%d/%d]-Iter[%d/%d] loss_content:%f, loss_style:%f"%(num_epoch, 
                            self.config.total_epoch, num_iter, iter_epoch, loss_content, loss_style)
                    )

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                
            if num_epoch % self.config.log_interval == 0:
                now = datetime.datetime.now()
                otherStyleTime = now.strftime("%Y-%m-%d %H:%M:%S")
                print(otherStyleTime)
                print('epoch: ',num_epoch ,' iter: ',num_iter)
                print('attention scartters: ', torch.std(attention_map.argmax(-1).float(), 1).mean().cpu())
                print(attention_map.shape)

                self.attention1.hard = True
                self.attention1.eval()
                self.encoder.eval()
                self.decoder.eval()

                tosave,perc,cont = self.eval()
                save_image(denorm(tosave), self.image_dir+'/epoch_{}-iter_{}.png'.format(num_epoch,num_iter))
                print("image saved to " + self.image_dir + '/epoch_{}-iter_{}.png'.format(num_epoch,num_iter))
                print('content loss:', cont)
                print('perceptual loss:', perc)

                self.reporter.writeTrainLog(num_epoch,num_iter,f'''
                    attention scartters: {torch.std(attention_map.argmax(-1).float(), 1).mean().cpu()}\n
                    content loss: {cont}\n
                    perceptual loss: {perc}
                ''')

                losses['perceptual'].append(perc)
                losses['content'].append(cont)
                self.plot_loss_curve(losses)

                self.attention1.hard = False
                self.attention1.train()
                self.encoder.train()
                self.decoder.train()

                torch.save({'layer1':self.attention1.state_dict(),
                            'encoder':self.encoder.state_dict(),
                            'decoder':self.decoder.state_dict()}, 
                                f'{self.model_state_dir}/epoch_{num_epoch}-iter_{num_iter}.pth')
                print('model saved.')