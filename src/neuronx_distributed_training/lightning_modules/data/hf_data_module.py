# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import datasets
import torch
from neuronx_distributed.parallel_layers import parallel_state
from torch.utils.data import DistributedSampler
from torch.utils.data.dataloader import DataLoader
from transformers import default_data_collator

from .base import BaseDataModule


class HFDataModule(BaseDataModule):
    def _build_dataloader(self, data):
        sampler = DistributedSampler(
            data,
            num_replicas=int(self.dp_size),
            rank=parallel_state.get_data_parallel_rank(),
            shuffle=False,
            drop_last=True,
        )

        return DataLoader(
            data,
            collate_fn=default_data_collator,
            sampler=sampler,
            batch_size=int(self.config.data.global_batch_size / self.dp_size),
            num_workers=0,
            drop_last=True,
            pin_memory=True,
        )

    def train_dataloader(self):
        self._train_ds = datasets.load_from_disk(self.config.data.train_dir)
        return self._build_dataloader(self._train_ds)

    def val_dataloader(self):
        self._validation_ds = datasets.load_from_disk(self.config.data.val_dir)
        return self._build_dataloader(self._validation_ds)

    def test_dataloader(self):
        self._test_ds = datasets.load_from_disk(self.config.data.test_dir)
        return self._build_dataloader(self._test_ds)
    
    def get_batch_length(self, batch):
        return len(batch["input_ids"])
    
    def process_global_batch(self, global_batch, global_batch_size=None):
        """Prepares the global batch for apex fwd/bwd functions.
        Global batch is a list of micro batches.
        """
        input_ids, attention_mask, labels = global_batch.values()
        loss_mask = torch.ones(labels.size(), dtype=torch.float)
        # set the lables with -100 as 0.0            
        loss_mask[labels == -100] = 0.0            
        seq_length = input_ids.numel()
        position_ids = torch.arange(seq_length, dtype=torch.int64).repeat(input_ids.shape[0], 1)
        return [
            input_ids,
            labels,
            loss_mask,
            attention_mask,
            position_ids,
        ]
