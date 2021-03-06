from argparse import ArgumentParser, Namespace
from data import UDDataModule
from functools import partial
from pytorch_lightning import seed_everything, Trainer
from pytorch_lightning.callbacks import EarlyStopping, ModelCheckpoint
from pytorch_lightning.loggers import TensorBoardLogger
from transformers import AutoTokenizer, logging
from utils import get_experiment_name

import models
import os
import torch

os.environ["TOKENIZERS_PARALLELISM"] = "false"
logging.set_verbosity_error()


def train(args: Namespace):
    seed_everything(args.seed, workers=True)

    # Load the tokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.encoder_name, add_prefix_space=True)
    tokenize_fn = partial(tokenizer, is_split_into_words=True, return_tensors="pt", padding=True)

    # Load the PL datamodule
    ud = UDDataModule(
        args.task,
        args.treebank_name,
        tokenize_fn,
        args.data_dir,
        args.batch_size,
        args.num_workers,
    )

    ud.prepare_data()
    ud.setup("fit")

    # Load the model class constructor
    if args.task == "DEP":
        model_class = models.DEPClassifier
    elif args.task == "POS":
        model_class = models.POSClassifier
    else:
        raise Exception(f"Unsupported task: {args.task}")

    # Load the BERT encoder
    bert = models.BERTEncoderForWordClassification(**vars(args))

    # Load the PL module
    if args.checkpoint:
        print(f"Loading from checkpoint: {args.checkpoint}")
        model = model_class.load_from_checkpoint(args.checkpoint)
    else:
        model_args = {
            "n_hidden": bert.hidden_size,
            "n_classes": ud.num_classes,
            "class_map": ud.id_to_cname,
            **vars(args),
        }

        # Ignore "root" predictions for the loss/accuracy in the DEP task
        if args.task == "DEP":
            model_args["ignore_idx"] = ud.cname_to_id["root"]

        model = model_class(**model_args)

    model.set_encoder(bert)

    # configure logger
    logger = TensorBoardLogger(
        save_dir=os.path.join(args.log_dir, args.encoder_name, args.treebank_name, args.task),
        name=get_experiment_name(args),
        default_hp_metric=False,
    )

    # Configure the callbacks
    callback_cfg = {"monitor": "val_acc", "mode": "max"}
    es_cb = EarlyStopping(**callback_cfg)  # TODO: maybe setup other early stopping parameters
    ckpt_cb = ModelCheckpoint(save_top_k=1, **callback_cfg)

    # Configure GPU usage
    use_gpu = 0 if args.no_gpu or (not torch.cuda.is_available()) else 1

    # Set up the trainer
    trainer = Trainer.from_argparse_args(
        args,
        logger=logger,
        gpus=use_gpu,
        callbacks=[es_cb, ckpt_cb],
    )

    trainer_args = {}
    if args.checkpoint:
        trainer_args["ckpt_path"] = args.checkpoint

    # Fit the model
    trainer.fit(model, ud, **trainer_args)


if __name__ == "__main__":
    parser = ArgumentParser()

    # Trainer arguments
    parser.add_argument("--checkpoint", type=str, help="The checkpoint from which to load a model.")

    parser.add_argument(
        "--enable_progress_bar",
        action="store_true",
        help="Whether to enable the progress bar (NOT recommended when logging to file).",
    )

    parser.add_argument(
        "--log_dir",
        type=str,
        default="./lightning_logs",
        help="The logging directory for Pytorch Lightning.",
    )

    parser.add_argument(
        "--log_every_n_steps",
        type=int,
        default=50,
        help="The number of steps (batches) between logging to tensorboard.",
    )

    parser.add_argument(
        "--max_epochs",
        type=int,
        default=20,
        help="The max amount of epochs to train the classifier.",
    )

    parser.add_argument(
        "--no_gpu",
        action="store_true",
        help="Whether to NOT use a GPU accelerator for training.",
    )

    parser.add_argument("--seed", type=int, default=420, help="The seed to use for the RNG.")

    # Encoder arguments
    models.BERTEncoderForWordClassification.add_model_specific_args(parser)

    # Classifier arguments
    models.BaseClassifier.add_model_specific_args(parser)
    models.DEPClassifier.add_model_specific_args(parser)

    # Dataset arguments
    UDDataModule.add_model_specific_args(parser)

    args = parser.parse_args()

    os.makedirs(args.data_dir, exist_ok=True)
    os.makedirs(args.log_dir, exist_ok=True)

    train(args)
