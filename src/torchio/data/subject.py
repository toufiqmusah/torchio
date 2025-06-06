from __future__ import annotations

import copy
import pprint
from collections.abc import Sequence
from typing import TYPE_CHECKING
from typing import Any

import numpy as np

from ..constants import INTENSITY
from ..constants import TYPE
from ..utils import get_subclasses
from .image import Image

if TYPE_CHECKING:
    from ..transforms import Compose
    from ..transforms import Transform


class Subject(dict):
    """Class to store information about the images corresponding to a subject.

    Args:
        *args: If provided, a dictionary of items.
        **kwargs: Items that will be added to the subject sample.

    Example:

        >>> import torchio as tio
        >>> # One way:
        >>> subject = tio.Subject(
        ...     one_image=tio.ScalarImage('path_to_image.nii.gz'),
        ...     a_segmentation=tio.LabelMap('path_to_seg.nii.gz'),
        ...     age=45,
        ...     name='John Doe',
        ...     hospital='Hospital Juan Negrín',
        ... )
        >>> # If you want to create the mapping before, or have spaces in the keys:
        >>> subject_dict = {
        ...     'one image': tio.ScalarImage('path_to_image.nii.gz'),
        ...     'a segmentation': tio.LabelMap('path_to_seg.nii.gz'),
        ...     'age': 45,
        ...     'name': 'John Doe',
        ...     'hospital': 'Hospital Juan Negrín',
        ... }
        >>> subject = tio.Subject(subject_dict)
    """

    def __init__(self, *args, **kwargs: dict[str, Any]):
        if args:
            if len(args) == 1 and isinstance(args[0], dict):
                kwargs.update(args[0])
            else:
                message = 'Only one dictionary as positional argument is allowed'
                raise ValueError(message)
        super().__init__(**kwargs)
        self._parse_images(self.get_images(intensity_only=False))
        self.update_attributes()  # this allows me to do e.g. subject.t1
        self.applied_transforms: list[tuple[str, dict]] = []

    def __repr__(self):
        num_images = len(self.get_images(intensity_only=False))
        string = (
            f'{self.__class__.__name__}'
            f'(Keys: {tuple(self.keys())}; images: {num_images})'
        )
        return string

    def __len__(self):
        return len(self.get_images(intensity_only=False))

    def __getitem__(self, item):
        if isinstance(item, (slice, int, tuple)):
            try:
                self.check_consistent_spatial_shape()
            except RuntimeError as e:
                message = (
                    'To use indexing, all images in the subject must have the'
                    ' same spatial shape'
                )
                raise RuntimeError(message) from e
            copied = copy.deepcopy(self)
            for image_name, image in copied.items():
                copied[image_name] = image[item]
            return copied
        else:
            return super().__getitem__(item)

    @staticmethod
    def _parse_images(images: list[Image]) -> None:
        # Check that it's not empty
        if not images:
            raise TypeError('A subject without images cannot be created')

    @property
    def shape(self):
        """Return shape of first image in subject.

        Consistency of shapes across images in the subject is checked first.

        Example:

            >>> import torchio as tio
            >>> colin = tio.datasets.Colin27()
            >>> colin.shape
            (1, 181, 217, 181)
        """
        self.check_consistent_attribute('shape')
        return self.get_first_image().shape

    @property
    def spatial_shape(self):
        """Return spatial shape of first image in subject.

        Consistency of spatial shapes across images in the subject is checked
        first.

        Example:

            >>> import torchio as tio
            >>> colin = tio.datasets.Colin27()
            >>> colin.spatial_shape
            (181, 217, 181)
        """
        self.check_consistent_spatial_shape()
        return self.get_first_image().spatial_shape

    @property
    def spacing(self):
        """Return spacing of first image in subject.

        Consistency of spacings across images in the subject is checked first.

        Example:

            >>> import torchio as tio
            >>> colin = tio.datasets.Slicer()
            >>> colin.spacing
            (1.0, 1.0, 1.2999954223632812)
        """
        self.check_consistent_attribute('spacing')
        return self.get_first_image().spacing

    @property
    def history(self):
        # Kept for backwards compatibility
        return self.get_applied_transforms()

    def is_2d(self):
        return all(i.is_2d() for i in self.get_images(intensity_only=False))

    def get_applied_transforms(
        self,
        ignore_intensity: bool = False,
        image_interpolation: str | None = None,
    ) -> list[Transform]:
        from ..transforms.intensity_transform import IntensityTransform
        from ..transforms.transform import Transform

        name_to_transform = {cls.__name__: cls for cls in get_subclasses(Transform)}
        transforms_list = []
        for transform_name, arguments in self.applied_transforms:
            transform = name_to_transform[transform_name](**arguments)
            if ignore_intensity and isinstance(transform, IntensityTransform):
                continue
            resamples = hasattr(transform, 'image_interpolation')
            if resamples and image_interpolation is not None:
                parsed = transform.parse_interpolation(image_interpolation)
                transform.image_interpolation = parsed
            transforms_list.append(transform)
        return transforms_list

    def get_composed_history(
        self,
        ignore_intensity: bool = False,
        image_interpolation: str | None = None,
    ) -> Compose:
        from ..transforms.augmentation.composition import Compose

        transforms = self.get_applied_transforms(
            ignore_intensity=ignore_intensity,
            image_interpolation=image_interpolation,
        )
        return Compose(transforms)

    def get_inverse_transform(
        self,
        warn: bool = True,
        ignore_intensity: bool = False,
        image_interpolation: str | None = None,
    ) -> Compose:
        """Get a reversed list of the inverses of the applied transforms.

        Args:
            warn: Issue a warning if some transforms are not invertible.
            ignore_intensity: If ``True``, all instances of
                :class:`~torchio.transforms.intensity_transform.IntensityTransform`
                will be ignored.
            image_interpolation: Modify interpolation for scalar images inside
                transforms that perform resampling.
        """
        history_transform = self.get_composed_history(
            ignore_intensity=ignore_intensity,
            image_interpolation=image_interpolation,
        )
        inverse_transform = history_transform.inverse(warn=warn)
        return inverse_transform

    def apply_inverse_transform(self, **kwargs) -> Subject:
        """Apply the inverse of all applied transforms, in reverse order.

        Args:
            **kwargs: Keyword arguments passed on to
                :meth:`~torchio.data.subject.Subject.get_inverse_transform`.
        """
        inverse_transform = self.get_inverse_transform(**kwargs)
        transformed: Subject
        transformed = inverse_transform(self)  # type: ignore[assignment]
        transformed.clear_history()
        return transformed

    def clear_history(self) -> None:
        self.applied_transforms = []

    def check_consistent_attribute(
        self,
        attribute: str,
        relative_tolerance: float = 1e-6,
        absolute_tolerance: float = 1e-6,
        message: str | None = None,
    ) -> None:
        r"""Check for consistency of an attribute across all images.

        Args:
            attribute: Name of the image attribute to check
            relative_tolerance: Relative tolerance for :func:`numpy.allclose()`
            absolute_tolerance: Absolute tolerance for :func:`numpy.allclose()`

        Example:
            >>> import numpy as np
            >>> import torch
            >>> import torchio as tio
            >>> scalars = torch.randn(1, 512, 512, 100)
            >>> mask = torch.tensor(scalars > 0).type(torch.int16)
            >>> af1 = np.eye([0.8, 0.8, 2.50000000000001, 1])
            >>> af2 = np.eye([0.8, 0.8, 2.49999999999999, 1])  # small difference here (e.g. due to different reader)
            >>> subject = tio.Subject(
            ...   image = tio.ScalarImage(tensor=scalars, affine=af1),
            ...   mask = tio.LabelMap(tensor=mask, affine=af2)
            ... )
            >>> subject.check_consistent_attribute('spacing')  # no error as tolerances are > 0

        .. note:: To check that all values for a specific attribute are close
            between all images in the subject, :func:`numpy.allclose()` is used.
            This function returns ``True`` if
            :math:`|a_i - b_i| \leq t_{abs} + t_{rel} * |b_i|`, where
            :math:`a_i` and :math:`b_i` are the :math:`i`-th element of the same
            attribute of two images being compared,
            :math:`t_{abs}` is the ``absolute_tolerance`` and
            :math:`t_{rel}` is the ``relative_tolerance``.
        """
        message = (
            f'More than one value for "{attribute}" found in subject images:\n{{}}'
        )

        names_images = self.get_images_dict(intensity_only=False).items()
        try:
            first_attribute = None
            first_image = None

            for image_name, image in names_images:
                if first_attribute is None:
                    first_attribute = getattr(image, attribute)
                    first_image = image_name
                    continue
                current_attribute = getattr(image, attribute)
                all_close = np.allclose(
                    current_attribute,
                    first_attribute,
                    rtol=relative_tolerance,
                    atol=absolute_tolerance,
                )
                if not all_close:
                    message = message.format(
                        pprint.pformat(
                            {
                                first_image: first_attribute,
                                image_name: current_attribute,
                            }
                        ),
                    )
                    raise RuntimeError(message)
        except TypeError:
            # fallback for non-numeric values
            values_dict = {}
            for image_name, image in names_images:
                values_dict[image_name] = getattr(image, attribute)
            num_unique_values = len(set(values_dict.values()))
            if num_unique_values > 1:
                message = message.format(pprint.pformat(values_dict))
                raise RuntimeError(message) from None

    def check_consistent_spatial_shape(self) -> None:
        self.check_consistent_attribute('spatial_shape')

    def check_consistent_orientation(self) -> None:
        self.check_consistent_attribute('orientation')

    def check_consistent_affine(self) -> None:
        self.check_consistent_attribute('affine')

    def check_consistent_space(self) -> None:
        try:
            self.check_consistent_attribute('spacing')
            self.check_consistent_attribute('direction')
            self.check_consistent_attribute('origin')
            self.check_consistent_spatial_shape()
        except RuntimeError as e:
            message = (
                'As described above, some images in the subject are not in the'
                ' same space. You probably can use the transforms ToCanonical'
                ' and Resample to fix this, as explained at'
                ' https://github.com/TorchIO-project/torchio/issues/647#issuecomment-913025695'
            )
            raise RuntimeError(message) from e

    def get_images_names(self) -> list[str]:
        return list(self.get_images_dict(intensity_only=False).keys())

    def get_images_dict(
        self,
        intensity_only=True,
        include: Sequence[str] | None = None,
        exclude: Sequence[str] | None = None,
    ) -> dict[str, Image]:
        images = {}
        for image_name, image in self.items():
            if not isinstance(image, Image):
                continue
            if intensity_only and not image[TYPE] == INTENSITY:
                continue
            if include is not None and image_name not in include:
                continue
            if exclude is not None and image_name in exclude:
                continue
            images[image_name] = image
        return images

    def get_images(
        self,
        intensity_only=True,
        include: Sequence[str] | None = None,
        exclude: Sequence[str] | None = None,
    ) -> list[Image]:
        images_dict = self.get_images_dict(
            intensity_only=intensity_only,
            include=include,
            exclude=exclude,
        )
        return list(images_dict.values())

    def get_first_image(self) -> Image:
        return self.get_images(intensity_only=False)[0]

    def add_transform(
        self,
        transform: Transform,
        parameters_dict: dict,
    ) -> None:
        self.applied_transforms.append((transform.name, parameters_dict))

    def load(self) -> None:
        """Load images in subject on RAM."""
        for image in self.get_images(intensity_only=False):
            image.load()

    def unload(self) -> None:
        """Unload images in subject."""
        for image in self.get_images(intensity_only=False):
            image.unload()

    def update_attributes(self) -> None:
        # This allows to get images using attribute notation, e.g. subject.t1
        self.__dict__.update(self)

    @staticmethod
    def _check_image_name(image_name):
        if not isinstance(image_name, str):
            message = (
                f'The image name must be a string, but it has type "{type(image_name)}"'
            )
            raise ValueError(message)
        return image_name

    def add_image(self, image: Image, image_name: str) -> None:
        """Add an image to the subject instance."""
        if not isinstance(image, Image):
            message = (
                'Image must be an instance of torchio.Image,'
                f' but its type is "{type(image)}"'
            )
            raise ValueError(message)
        self._check_image_name(image_name)
        self[image_name] = image
        self.update_attributes()

    def remove_image(self, image_name: str) -> None:
        """Remove an image from the subject instance."""
        self._check_image_name(image_name)
        del self[image_name]
        delattr(self, image_name)

    def plot(self, **kwargs) -> None:
        """Plot images using matplotlib.

        Args:
            **kwargs: Keyword arguments that will be passed on to
                :meth:`~torchio.Image.plot`.
        """
        from ..visualization import plot_subject  # avoid circular import

        plot_subject(self, **kwargs)
