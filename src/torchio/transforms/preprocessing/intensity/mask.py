from __future__ import annotations

import warnings
from collections.abc import Sequence

import torch

from ....data.image import ScalarImage
from ....data.subject import Subject
from ....transforms.transform import TypeMaskingMethod
from ...intensity_transform import IntensityTransform


class Mask(IntensityTransform):
    """Set voxels outside of mask to a constant value.

    Args:
        masking_method: See
            :class:`~torchio.transforms.preprocessing.intensity.NormalizationTransform`.
        outside_value: Value to set for all voxels outside of the mask.
        labels: If a label map is used to generate the mask,
            sequence of labels to consider. If ``None``, all values larger than
            zero will be used for the mask.
        **kwargs: See :class:`~torchio.transforms.Transform` for additional
            keyword arguments.

    Raises:
        RuntimeWarning: If a 4D image is masked with a 3D mask, the mask will
            be expanded along the channels (first) dimension, and a warning
            will be raised.

    Example:
        >>> import torchio as tio
        >>> subject = tio.datasets.Colin27()
        >>> subject
        Colin27(Keys: ('t1', 'head', 'brain'); images: 3)
        >>> mask = tio.Mask(masking_method='brain')  # Use "brain" image to mask
        >>> transformed = mask(subject)  # Set voxels outside of the brain to 0

    .. plot::

        import torchio as tio
        subject = tio.datasets.Colin27()
        subject.remove_image('head')
        mask = tio.Mask('brain')
        masked = mask(subject)
        subject.add_image(masked.t1, 'Masked')
        subject.plot()
    """

    def __init__(
        self,
        masking_method: TypeMaskingMethod,
        outside_value: float = 0,
        labels: Sequence[int] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.masking_method = masking_method
        self.masking_labels = labels
        self.outside_value = outside_value
        self.args_names = ['masking_method']

    def apply_transform(self, subject: Subject) -> Subject:
        for image in self.get_images(subject):
            mask_data = self.get_mask_from_masking_method(
                self.masking_method,
                subject,
                image.data,
                self.masking_labels,
            )
            assert isinstance(image, ScalarImage)
            self.apply_masking(image, mask_data)
        return subject

    def apply_masking(
        self,
        image: ScalarImage,
        mask_data: torch.Tensor,
    ) -> None:
        masked = mask(image.data, mask_data, self.outside_value)
        image.set_data(masked)


def mask(
    tensor: torch.Tensor,
    mask: torch.Tensor,
    outside_value: float,
) -> torch.Tensor:
    array = tensor.clone()
    num_channels_array = array.shape[0]
    num_channels_mask = mask.shape[0]
    if num_channels_array != num_channels_mask:
        assert num_channels_mask == 1
        message = (
            f'Expanding mask with shape {mask.shape}'
            f' to match shape {array.shape} of input image'
        )
        warnings.warn(message, RuntimeWarning, stacklevel=2)
        mask = mask.expand(*array.shape)
    array[~mask] = outside_value
    return array
