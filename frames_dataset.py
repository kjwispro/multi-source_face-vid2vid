import os
from skimage import io, img_as_float32
from skimage.color import gray2rgb
from sklearn.model_selection import train_test_split
from imageio import mimread

import numpy as np
import torch
from torch.utils.data import Dataset


import pandas as pd
from augmentation import AllAugmentationTransform
import glob



def read_video(name, frame_shape):
    """
    Read video which can be:
      - an image of concatenated frames
      - '.mp4' and'.gif'
      - folder with videos
    """

    if os.path.isdir(name):
        frames = sorted(os.listdir(name))
        num_frames = len(frames)
        video_array = np.array(
            [img_as_float32(io.imread(os.path.join(name, frames[idx]))) for idx in range(num_frames)])
    elif name.lower().endswith('.png') or name.lower().endswith('.jpg'):
        image = io.imread(name)

        if len(image.shape) == 2 or image.shape[2] == 1:
            image = gray2rgb(image)

        if image.shape[2] == 4:
            image = image[..., :3]

        image = img_as_float32(image)

        video_array = np.moveaxis(image, 1, 0)

        video_array = video_array.reshape((-1,) + frame_shape)
        video_array = np.moveaxis(video_array, 1, 2)
    elif name.lower().endswith('.gif') or name.lower().endswith('.mp4') or name.lower().endswith('.mov'):
        video = np.array(mimread(name))
        if len(video.shape) == 3:
            video = np.array([gray2rgb(frame) for frame in video])
        if video.shape[-1] == 4:
            video = video[..., :3]
        video_array = img_as_float32(video)
    else:
        raise Exception("Unknown file extensions  %s" % name)

    return video_array


class FramesDataset(Dataset):
    """
    Dataset of videos, each video can be represented as:
      - an image of concatenated frames
      - '.mp4' or '.gif'
      - folder with all frames
    """

    def __init__(self, root_dir, frame_shape=(256, 256, 3), id_sampling=False, is_train=True,
                 random_seed=0, pairs_list=None, augmentation_params=None, source_paths=None, num_source=1):
        self.root_dir = root_dir
        self.videos = os.listdir(root_dir)
        self.frame_shape = tuple(frame_shape)
        self.pairs_list = pairs_list
        self.num_source = num_source
        self.id_sampling = id_sampling
        self.source_paths = source_paths
        self.zero_frame = []
        if num_source > 1:
            assert source_paths is not None
        if os.path.exists(os.path.join(root_dir, 'train')):
            assert os.path.exists(os.path.join(root_dir, 'test'))
            print("Use predefined train-test split.")
            if id_sampling:
                train_videos = {os.path.basename(video).split('#')[0] for video in
                                os.listdir(os.path.join(root_dir, 'train'))}
                train_videos = list(train_videos)
            else:
                train_videos = os.listdir(os.path.join(root_dir, 'train'))
            test_videos = os.listdir(os.path.join(root_dir, 'test'))
            self.root_dir = os.path.join(self.root_dir, 'train' if is_train else 'test')
            # self.max_num_frame = self.calculate_max_frame(self.root_dir, train_videos)
        else:
            print("Use random train-test split.")
            train_videos, test_videos = train_test_split(self.videos, random_state=random_seed, test_size=0.2)

        if is_train:
            self.videos = train_videos
        else:
            self.videos = test_videos

        self.is_train = is_train

        if self.is_train:
            self.transform = AllAugmentationTransform(**augmentation_params)
        else:
            self.transform = None
        
    def calculate_max_frame(self, root_dir, train_videos):
        num_frames = []
        for name in train_videos:
            path = np.random.choice(glob.glob(os.path.join(self.root_dir, name + '*.mp4')))
            frames = os.listdir(path)
            num_frames.append(len(frames))
            print(path, num_frames[-1])
        return max(num_frames)

    def __len__(self):
        return len(self.videos)

    def __getitem__(self, idx):
        if self.is_train and self.id_sampling:
            name = self.videos[idx]
            path = np.random.choice(glob.glob(os.path.join(self.root_dir, name + '*.mp4')))
        else:
            name = self.videos[idx]
            path = os.path.join(self.root_dir, name)

        video_name = os.path.basename(path)

        if self.is_train and os.path.isdir(path):
            frames = os.listdir(path)
            num_frames = len(frames)
            if num_frames == 0:
                video_array = [np.zeros((256, 256, 3)), np.zeros((256, 256, 3))]
                select_names = ['','']
                self.zero_frame.append(path)
                self.zero_frame = list(set(self.zero_frame))
            else:
                if self.num_source == 1:
                    frame_idx = np.sort(np.random.choice(num_frames, replace=True, size=2))
                    video_array = [img_as_float32(io.imread(os.path.join(path, frames[idx].decode()))) for idx in frame_idx]
                    select_names = [os.path.join(path, frames[idx].decode()) for idx in frame_idx]
                else:
                    video_array = [img_as_float32(io.imread(frame_path)) for frame_path in self.source_paths[path.split('/')[5]]['center_img_path']]
                    select_names = [frame_path for frame_path in self.source_paths[path.split('/')[5]]['center_img_path']]
        else:
            video_array = read_video(path, frame_shape=self.frame_shape)
            num_frames = len(video_array)
            frame_idx = np.sort(np.random.choice(num_frames, replace=True, size=2)) if self.is_train else range(
                num_frames)
            video_array = video_array[frame_idx]

        if self.transform is not None:
            video_array = self.transform(video_array)

        out = {}

        # original
        
        if self.is_train:
            if self.num_source == 1:
                source = np.array(video_array[0], dtype='float32')
                driving = np.array(video_array[1], dtype='float32')

                out['driving'] = driving.transpose((2, 0, 1))
                out['source'] = source.transpose((2, 0, 1))
            else:
                source = np.array(video_array[:self.num_source], dtype='float32')
                driving = np.array(video_array[-1], dtype='float32')

                out['driving'] = driving.transpose((2, 0, 1))
                out['source'] = source.transpose((0, 3, 1, 2))

        else:
            video = np.array(video_array, dtype='float32')
            out['video'] = video.transpose((3, 0, 1, 2))

        out['name'] = video_name
        out['select_paths'] = select_names
        return out
    



class DatasetRepeater(Dataset):
    """
    Pass several times over the same dataset for better i/o performance
    """

    def __init__(self, dataset, num_repeats=100):
        self.dataset = dataset
        self.num_repeats = num_repeats

    def __len__(self):
        return self.num_repeats * self.dataset.__len__()

    def __getitem__(self, idx):
        return self.dataset[idx % self.dataset.__len__()]
