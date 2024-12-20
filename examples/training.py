# Copyright (c) 2021, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import os


import torch
from lightning_lite.plugins.environments import TorchElasticEnvironment
from nemo.utils import logging
from nemo.utils.exp_manager import StatelessTimer
from omegaconf.omegaconf import OmegaConf, open_dict
from pytorch_lightning.callbacks.timer import Timer

from neuronx_distributed_training.lightning_modules.data.megatron import MegatronDataModule
from neuronx_distributed_training.lightning_modules.model.megatron import MegatronGPTModel
from neuronx_distributed_training.lightning_modules.data.hf_data_module import HFDataModule
from neuronx_distributed_training.lightning_modules.data.sft_data_module import SFTDataModule
from neuronx_distributed_training.lightning_modules.model.hf_models.llama_model import HFLLamaModule
from neuronx_distributed_training.lightning_modules.model.hf_models.mistral_model import HFMistralModule
from neuronx_distributed_training.lightning_modules.nlp_overrides import (
    NLPCheckpointIO,
    NLPDDPStrategy,
    NLPTrainer,
)
from neuronx_distributed_training.utils.exp_manager import exp_manager

def train(cfg) -> None:
    logging.info("\n\n************** Experiment configuration ***********")
    logging.info(f"\n{OmegaConf.to_yaml(cfg)}")
    plugins = []

    nlp_xla_checkpoint_io = NLPCheckpointIO(
        cfg.exp_manager.get("async_checkpointing", False), 
        cfg.model.get("weight_init_only", False)
    )
    cluster_environment = None
    if os.environ.get("TORCHELASTIC_RUN_ID") is not None:
        cluster_environment = TorchElasticEnvironment()
    strategy = NLPDDPStrategy(
        find_unused_parameters=False,
        cluster_environment=cluster_environment,
        checkpoint_io=nlp_xla_checkpoint_io,
        restore_path=cfg.exp_manager.resume_from_checkpoint,
    )

    # Update resume from checkpoint found by exp_manager
    if cfg.exp_manager.resume_from_checkpoint is not None:
        resume_from_checkpoint = cfg.exp_manager.resume_from_checkpoint
        trainer = NLPTrainer(
            plugins=plugins, strategy=strategy, resume_from_checkpoint=resume_from_checkpoint, **cfg.trainer
        )
    else:
        trainer = NLPTrainer(plugins=plugins, strategy=strategy, **cfg.trainer)

    exp_manager(trainer, cfg.exp_manager)
    
    for idx, callback in enumerate(trainer.callbacks):
        if isinstance(callback, Timer):
            trainer.callbacks[idx] = StatelessTimer(cfg.trainer.max_time)

    if cfg.model_source == 'megatron':
        if getattr(cfg.data, "use_sft_style_data_module", False):
            data_module = SFTDataModule(cfg, trainer)
        else:
            data_module = MegatronDataModule(cfg, trainer)
        model = MegatronGPTModel(cfg, trainer)
    elif cfg.model_source == 'hf':
        if getattr(cfg.data, "use_sft_style_data_module", False):
            data_module = SFTDataModule(cfg, trainer)
        else:
            data_module = HFDataModule(cfg, trainer)

        # Support for both HFMistralModule and HFLLamaModule
        if cfg.name == 'hf_llama':
            model = HFLLamaModule(cfg, trainer)
        elif cfg.name == 'hf_mistral':
            model = HFMistralModule(cfg, trainer)
        else:
            raise ValueError(f"Unsupported HF model type: {cfg.model.type}")

    else:
        raise NotImplementedError

    trainer.fit(model, datamodule=data_module)
