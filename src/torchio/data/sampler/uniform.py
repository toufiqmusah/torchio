from __future__ import annotations

from collections.abc import Generator

import torch

from ...data.subject import Subject
from .sampler import RandomSampler


class UniformSampler(RandomSampler):
    """Randomly extract patches from a volume with uniform probability.

    Args:
        patch_size: See :class:`~torchio.data.PatchSampler`.
    """

    def get_probability_map(self, subject: Subject) -> torch.Tensor:
        return torch.ones(1, *subject.spatial_shape)

    def _generate_patches(
        self,
        subject: Subject,
        num_patches: int | None = None,
    ) -> Generator[Subject]:
        valid_range = subject.spatial_shape - self.patch_size
        patches_left = num_patches if num_patches is not None else True
        while patches_left:
            i, j, k = tuple(int(torch.randint(x + 1, (1,)).item()) for x in valid_range)
            index_ini = i, j, k
            yield self.extract_patch(subject, index_ini)
            if num_patches is not None:
                patches_left -= 1
