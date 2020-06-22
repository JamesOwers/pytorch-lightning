import pytest

import torch
import tests.base.utils as tutils
from pytorch_lightning import Callback
from pytorch_lightning import Trainer, LightningModule
from pytorch_lightning.callbacks import EarlyStopping, LearningRateLogger, ModelCheckpoint
from pytorch_lightning.loggers import TensorBoardLogger
from tests.base import EvalModelTemplate
from pathlib import Path


def test_resume_early_stopping_from_checkpoint(tmpdir):
    """
    Prevent regressions to bugs:
    https://github.com/PyTorchLightning/pytorch-lightning/issues/1464
    https://github.com/PyTorchLightning/pytorch-lightning/issues/1463
    """

    class EarlyStoppingTestRestore(EarlyStopping):
        def __init__(self, expected_state):
            super().__init__()
            self.expected_state = expected_state

        def on_train_start(self, trainer, pl_module):
            assert self.state_dict() == self.expected_state

    model = EvalModelTemplate()
    checkpoint_callback = ModelCheckpoint(save_top_k=1)
    early_stop_callback = EarlyStopping()
    trainer = Trainer(checkpoint_callback=checkpoint_callback, early_stop_callback=early_stop_callback, max_epochs=4)
    trainer.fit(model)
    early_stop_callback_state = early_stop_callback.state_dict()

    checkpoint_filepath = checkpoint_callback.kth_best_model
    # ensure state is persisted properly
    checkpoint = torch.load(checkpoint_filepath)
    assert checkpoint['early_stop_callback_state_dict'] == early_stop_callback_state
    # ensure state is reloaded properly (assertion in the callback)
    early_stop_callback = EarlyStoppingTestRestore(early_stop_callback_state)
    new_trainer = Trainer(max_epochs=2,
                          resume_from_checkpoint=checkpoint_filepath,
                          early_stop_callback=early_stop_callback)
    new_trainer.fit(model)


def test_early_stopping_no_extraneous_invocations():
    """Test to ensure that callback methods aren't being invoked outside of the callback handler."""
    class EarlyStoppingTestInvocations(EarlyStopping):
        def __init__(self, expected_count):
            super().__init__()
            self.count = 0
            self.expected_count = expected_count

        def on_validation_end(self, trainer, pl_module):
            self.count += 1

        def on_train_end(self, trainer, pl_module):
            assert self.count == self.expected_count

    model = EvalModelTemplate()
    expected_count = 4
    early_stop_callback = EarlyStoppingTestInvocations(expected_count)
    trainer = Trainer(early_stop_callback=early_stop_callback, val_check_interval=1.0, max_epochs=expected_count)
    trainer.fit(model)


@pytest.mark.parametrize('loss_values, patience, expected_stop_epoch', [
    ([6, 5, 5, 5, 5, 5], 3, 5),
    ([6, 5, 4, 4, 3, 3], 1, 4),
    ([6, 5, 6, 5, 5, 5], 3, 5),
])
def test_early_stopping_patience(loss_values, patience, expected_stop_epoch):
    """Test to ensure that early stopping is not triggered before patience is exhausted."""

    class ModelOverrideValidationReturn(EvalModelTemplate):
        validation_return_values = torch.Tensor(loss_values)
        count = 0

        def validation_epoch_end(self, outputs):
            loss = self.validation_return_values[self.count]
            self.count += 1
            return {"test_val_loss": loss}

    model = ModelOverrideValidationReturn()
    early_stop_callback = EarlyStopping(monitor="test_val_loss", patience=patience, verbose=True)
    trainer = Trainer(early_stop_callback=early_stop_callback, val_check_interval=1.0, num_sanity_val_steps=0, max_epochs=10)
    trainer.fit(model)
    assert trainer.current_epoch == expected_stop_epoch


def test_pickling(tmpdir):
    import pickle
    early_stopping = EarlyStopping()
    early_stopping_pickled = pickle.dumps(early_stopping)
    early_stopping_loaded = pickle.loads(early_stopping_pickled)
    assert vars(early_stopping) == vars(early_stopping_loaded)