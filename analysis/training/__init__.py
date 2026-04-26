"""analysis.training — Data collection pipeline for ML training from Hearthstone replays.

This package provides feature encoding and training data extraction without
any neural network model dependency.  It transforms parsed game states and
actions into fixed-length numeric vectors suitable for any downstream ML
framework.

Public API:
    - StateEncoder: encode GameState → 294-dim feature vector
    - ActionEncoder: encode Action → 13-dim feature vector
    - TrainingDataExtractor: extract TrainingSample objects from replay data
    - TrainingPipeline: batch-process Power.log files into training datasets
    - encode_ability_tag / pool_ability_tags: ability tag feature encoding
"""

from analysis.training.ability_tags import (
    ABILITY_TAG_DIM,
    EFFECT_KINDS,
    TARGET_KINDS,
    encode_ability_tag,
    effect_to_tag,
    pool_ability_tags,
)
from analysis.training.encoder import ActionEncoder, StateEncoder
from analysis.training.extractor import TrainingDataExtractor, TrainingSample
from analysis.training.pipeline import TrainingPipeline

__all__ = [
    # ability_tags
    "ABILITY_TAG_DIM",
    "EFFECT_KINDS",
    "TARGET_KINDS",
    "encode_ability_tag",
    "effect_to_tag",
    "pool_ability_tags",
    # encoder
    "StateEncoder",
    "ActionEncoder",
    # extractor
    "TrainingSample",
    "TrainingDataExtractor",
    # pipeline
    "TrainingPipeline",
]
