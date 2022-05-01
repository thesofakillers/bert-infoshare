from argparse import ArgumentParser, Namespace
from data import UDDataModule
from functools import partial
from model import POSClassifier
from pytorch_lightning import seed_everything, Trainer
from pytorch_lightning.callbacks import EarlyStopping, ModelCheckpoint
from pytorch_lightning.loggers import TensorBoardLogger
from transformers import AutoTokenizer

import os
os.environ['TOKENIZERS_PARALLELISM'] = 'false'


def train(args: Namespace):
    seed_everything(args.seed, workers=True)

    # load tokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.encoder_name, add_prefix_space=True)
    tokenize_fn = partial(tokenizer, is_split_into_words=True, return_tensors='pt', padding=True)

    # load PL datamodule
    ud = UDDataModule(args.treebank_name,
                      tokenize_fn,
                      tokenizer.pad_token,
                      args.data_dir,
                      args.batch_size,
                      args.num_workers,
                      args.enable_progress_bar,
                      )

    ud.prepare_data()
    ud.setup('fit')

    # load PL module
    if args.checkpoint:
        print(f'Loading from checkpoint: {args.checkpoint}')
        model = POSClassifier.load_from_checkpoint(args.checkpoint)
    else:
        model_args = {'n_classes': ud.num_classes, **vars(args)}
        model = POSClassifier(**model_args)

    # configure logger
    logger = TensorBoardLogger(args.log_dir, name=args.encoder_name, default_hp_metric=False)

    # configure callbacks
    callback_cfg = {'monitor': 'val_acc', 'mode': 'max'}
    es_cb = EarlyStopping(**callback_cfg)  # TODO: maybe setup other early stopping parameters
    ckpt_cb = ModelCheckpoint(save_top_k=1, **callback_cfg)

    # set up trainer
    trainer = Trainer.from_argparse_args(args,
                                         logger=logger,
                                         gpus=(0 if args.no_gpu else 1),
                                         callbacks=[es_cb, ckpt_cb],
                                         )

    trainer_args = {}
    if args.checkpoint:
        # THIS DOES NOT WORK IN PL 1.6.0 WHEN USING EARLY STOPPING OR AN LR SCHEDULER THAT MONITORS VAL LOSS/ACC
        # trainer_args['ckpt_path'] = args.checkpoint
        pass

    # fit
    trainer.fit(model, ud, **trainer_args)


if __name__ == '__main__':
    parser = ArgumentParser()

    # Trainer arguments
    parser.add_argument('--seed', type=int, default=420,
                        help='The seed to use for the RNG.')

    parser.add_argument('--max_epochs', type=int, default=20,
                        help='The max amount of epochs to train the classifier.')

    parser.add_argument('--enable_progress_bar', action='store_true', default=True,
                        help='Whether to enable the progress bar (NOT recommended when logging to file).')

    parser.add_argument('--no_gpu', action='store_true',
                        help='Whether to NOT use a GPU accelerator for training.')

    parser.add_argument('--checkpoint', type=str,
                        help='The checkpoint from which to load a model.')

    # Model arguments
    POSClassifier.add_model_specific_args(parser)

    parser.add_argument('--treebank_name', type=str, default='en_gum',
                        help='The name of the treebank to use as the dataset.')

    parser.add_argument('--batch_size', type=int, default=64,
                        help='The batch size used by the dataloaders.')

    parser.add_argument('--num_workers', type=int, default=4,
                        help='The number of subprocesses used by the dataloaders.')

    # Directory arguments
    parser.add_argument('--data_dir', type=str, default='./data',
                        help='The data directory to use for the datasets.')

    parser.add_argument('--log_dir', type=str, default='./lightning_logs',
                        help='The logging directory for Pytorch Lightning.')

    args = parser.parse_args()

    os.makedirs(args.data_dir, exist_ok=True)
    os.makedirs(args.log_dir, exist_ok=True)

    train(args)
