import os
import argparse
from PIL import Image
import numpy as np
from skimage import io, transform
from tqdm import tqdm
import joblib
import math

import torch
import torch.nn.functional as F
from torchvision import transforms,datasets
from torchvision.utils import save_image
import matplotlib.pyplot as plt

from model.VGG import Encoder
from model.Decoder import Decoder
from components.utils import *


class Trainer(object):
    def __init__(self, config):


        self.train_loader = torch.utils.data.DataLoader(
            datasets.ImageFolder(config.train_data_dir, transforms.Compose([
                transforms.RandomSizedCrop(config.image_size),
                transforms.RandomHorizontalFlip(),
                transforms.ToTensor(),
                normalize,
            ])),
            batch_size=config.batch_size, shuffle=True,
            num_workers=config.workers, pin_memory=True)

        os.makedirs(f'{config.save_dir}/{config.version}',exist_ok=True)

        self.loss_dir = f'{config.save_dir}/{config.version}/loss'
        self.model_state_dir = f'{config.save_dir}/{config.version}/model_state'
        self.image_dir = f'{config.save_dir}/{config.version}/image'
        self.psnr_dir = f'{config.save_dir}/{config.version}/psnr'

        os.makedirs(self.loss_dir,exist_ok=True)
        os.makedirs(self.model_state_dir,exist_ok=True)
        os.makedirs(self.image_dir,exist_ok=True)
        os.makedirs(self.psnr_dir,exist_ok=True)

        self.encoder = Encoder().cuda()
        self.decoder = Decoder().cuda()

        self.config = config

    def train(self):

        optimizer = torch.optim.Adam(self.decoder.parameters(), lr=self.config.learning_rate)
        criterion = torch.nn.L1Loss()#torch.nn.MSELoss()

        loss_list = []
        psnr_list = []
        self.encoder.eval()
        self.decoder.train()
        for e in range(1, self.config.epoch_size+1):
            print(f'Start {e} epoch')
            psnr_list = []
            # for i, (content, target)  in tqdm(enumerate(self.train_loader, 1)):
            for i, (content, target)  in enumerate(self.train_loader):
                content = content.cuda()
                content_feature = self.encoder(content)
                out_content = self.decoder(content_feature)

                loss = criterion(content, out_content)
                loss_list.append(loss.item())

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()


                with torch.no_grad():
                    if i%1000 == 0:
                        print(loss.item())
                        psnr = PSNR2(denorm(content).cpu().numpy(),denorm(out_content).cpu().numpy())
                        psnr_list.append(psnr)
                        print('psnr:',psnr)

            ori = torch.cat(list(denorm(content)), 2)
            out = torch.cat(list(denorm(out_content)), 2)
            save_image(torch.cat([ori,out], 1), self.image_dir+'/epoch_{}.png'.format(e))
            print("image saved to " + self.image_dir + '/epoch_{}.png'.format(e))

            torch.save(self.decoder.state_dict(), f'{self.model_state_dir}/{e}_epoch.pth')
            filename = 'psnr/e'+ str(e) + '.pkl'
            joblib.dump(psnr_list,os.path.join(self.config.save_dir,filename))

        self.plot_loss_curve(loss_list)

    def plot_loss_curve(self, loss_list):
        plt.plot(range(len(loss_list)), loss_list)
        plt.xlabel('iteration')
        plt.ylabel('loss')
        plt.title('train loss')
        plt.savefig(f'{self.loss_dir}/train_loss.png')
        with open(f'{self.loss_dir}/loss_log.txt', 'w') as f:
            for l in loss_list:
                f.write(f'{l}\n')
        print(f'Loss saved in {self.loss_dir}')   
