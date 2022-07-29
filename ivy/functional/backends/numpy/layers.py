"""Collection of Numpy network layers, wrapped to fit Ivy syntax and signature."""

# global
import numpy as np
from typing import Union, Tuple, Optional, List


def conv1d(
    x: np.ndarray,
    filters: np.ndarray,
    strides: int,
    padding: str,
    data_format: str = "NWC",
    dilations: int = 1,
    *,
    out: Optional[np.ndarray] = None
) -> np.ndarray:
    if isinstance(strides, tuple):
        strides = strides[0]
    if isinstance(dilations, tuple):
        dilations = dilations[0]
    if data_format == "NCW":
        x = np.transpose(x, (0, 2, 1))
    x_shape = (1,) + x.shape
    filter_shape = (1,) + filters.shape
    x_strides = (x.strides[0],) + x.strides
    filter_strides = (filters.strides[0],) + filters.strides
    x = np.lib.stride_tricks.as_strided(x, shape=x_shape, strides=x_strides)
    filters = np.lib.stride_tricks.as_strided(
        filters, shape=filter_shape, strides=filter_strides
    )
    x = np.transpose(x, (1, 0, 2, 3))
    res = conv2d(x, filters, strides, padding, "NHWC", dilations)
    res = np.transpose(res, (1, 0, 2, 3))
    res = np.lib.stride_tricks.as_strided(
        res, shape=res.shape[1:], strides=res.strides[1:]
    )
    if data_format == "NCW":
        res = np.transpose(res, (0, 2, 1))
    return res


def conv1d_transpose(*_):
    raise Exception("Convolutions not yet implemented for numpy library")


def conv2d(
    x: np.ndarray,
    filters: np.ndarray,
    strides: Union[int, Tuple[int, int]],
    padding: str,
    data_format: str = "NHWC",
    dilations: Optional[Union[int, Tuple[int], Tuple[int, int]]] = 1,
    *,
    out: Optional[np.ndarray] = None
) -> np.ndarray:
    if isinstance(strides, int):
        strides = (strides, strides)
    elif len(strides) == 1:
        strides = (strides[0], strides[0])

    if isinstance(dilations, int):
        dilations = (dilations, dilations)
    elif len(dilations) == 1:
        dilations = (dilations[0], dilations[0])

    # adding dilations
    if dilations[1] > 1:
        filters = np.insert(
            filters,
            [i for i in range(1, filters.shape[1])] * (dilations[1] - 1),
            values=0,
            axis=1,
        )
    if dilations[0] > 1:
        filters = np.insert(
            filters,
            [i for i in range(1, filters.shape[0])] * (dilations[0] - 1),
            values=0,
            axis=0,
        )

    filter_shape = filters.shape[0:2]
    filter_shape = list(filter_shape)

    if data_format == "NCHW":
        x = np.transpose(x, (0, 2, 3, 1))

    x_shape = list(x.shape[1:3])
    if padding == "SAME":
        if x_shape[1] % strides[1] == 0:
            pad_w = max(filter_shape[1] - strides[1], 0)
        else:
            pad_w = max(filter_shape[1] - (x_shape[1] % strides[1]), 0)

        if x_shape[0] % strides[0] == 0:
            pad_h = max(filter_shape[0] - strides[0], 0)
        else:
            pad_h = max(filter_shape[0] - (x_shape[0] % strides[0]), 0)
        x = np.pad(
            x,
            [
                (0, 0),
                (pad_h // 2, pad_h - pad_h // 2),
                (pad_w // 2, pad_w - pad_w // 2),
                (0, 0),
            ],
            "constant",
        )

    x_shape = x.shape
    input_dim = filters.shape[-2]
    output_dim = filters.shape[-1]
    new_h = (x_shape[1] - filter_shape[0]) // strides[0] + 1
    new_w = (x_shape[2] - filter_shape[1]) // strides[1] + 1
    new_shape = [x_shape[0], new_h, new_w] + filter_shape + [x_shape[-1]]
    new_strides = (
        x.strides[0],
        x.strides[1] * strides[1],
        x.strides[2] * strides[0],
        x.strides[1],
        x.strides[2],
        x.strides[3],
    )
    # B x OH x OW x KH x KW x I
    sub_matrices = np.lib.stride_tricks.as_strided(
        x, new_shape, new_strides, writeable=False
    )
    # B x OH x OW x KH x KW x I x O
    sub_matrices_w_output_dim = np.tile(
        np.expand_dims(sub_matrices, -1), [1] * 6 + [output_dim]
    )
    # B x OH x OW x KH x KW x I x O
    mult = sub_matrices_w_output_dim * filters.reshape(
        [1] * 3 + filter_shape + [input_dim, output_dim]
    )
    # B x OH x OW x O
    res = np.sum(mult, (3, 4, 5))
    if data_format == "NCHW":
        return np.transpose(res, (0, 3, 1, 2))
    return res


def depthwise_conv2d(
    x: np.ndarray,
    filters: np.ndarray,
    strides: Union[int, Tuple[int], Tuple[int, int]],
    padding: Union[str, List[int]],
    data_format: str = "NHWC",
    dilations: Optional[Union[int, Tuple[int], Tuple[int, int]]] = 1,
    *,
    out: Optional[np.ndarray] = None,
):
    strides = [strides] * 2 if isinstance(strides, int) else strides
    dilations = [dilations] * 2 if isinstance(dilations, int) else dilations

    if data_format == "NHWC":
        x = np.transpose(x, (3, 0, 1, 2))
    else:
        x = np.transpose(x, (1, 0, 2, 3))
    depth = x.shape[0]
    filters = np.transpose(filters, (2, 0, 1))
    x = np.expand_dims(x, -1)
    filters = np.expand_dims(filters, (-1, -2))
    x_shape = x[0].shape
    filter_shape = filters[0].shape
    filter_h = filter_shape[0] + (filter_shape[0] - 1) * (dilations[0] - 1)
    filter_w = filter_shape[1] + (filter_shape[1] - 1) * (dilations[1] - 1)
    if padding == "VALID":
        out_height = np.ceil(float(x_shape[1] - filter_h + 1) / float(strides[0]))
        out_width = np.ceil(float(x_shape[2] - filter_w + 1) / float(strides[1]))
    else:
        out_height = np.ceil(float(x_shape[1]) / float(strides[0]))
        out_width = np.ceil(float(x_shape[2]) / float(strides[1]))
    if data_format == "NHWC":
        outputs = np.empty([x_shape[0], int(out_height), int(out_width), 0], x.dtype)
    else:
        outputs = np.empty([x_shape[0], 0, int(out_height), int(out_width)], x.dtype)
    for i in range(depth):
        output = conv2d(x[i], filters[i], strides, padding, "NHWC", dilations)
        if data_format == "NHWC":
            outputs = np.append(outputs, output, axis=-1)
        else:
            outputs = np.append(
                outputs,
                np.transpose(
                    output,
                    (0, 3, 1, 2)
                ),
                axis=1
            )
    return outputs


def conv2d_transpose(*_):
    raise Exception("Convolutions not yet implemented for numpy library")


def conv3d(
    x: np.ndarray,
    filters: np.ndarray,
    strides: Union[int, Tuple[int, int, int]],
    padding: str,
    data_format: str = "NDHWC",
    dilations: Union[int, Tuple[int, int, int]] = 1,
    *,
    out: np.ndarray = None,
) -> np.ndarray:
    if isinstance(strides, int):
        strides = (strides, strides, strides)

    if isinstance(dilations, int):
        dilations = (dilations, dilations, dilations)

    # adding dilations
    if dilations[1] > 1:
        filters = np.insert(
            filters,
            [i for i in range(1, filters.shape[1])] * (dilations[1] - 1),
            values=0,
            axis=1
        )
    if dilations[0] > 1:
        filters = np.insert(
            filters,
            [i for i in range(1, filters.shape[0])] * (dilations[0] - 1),
            values=0,
            axis=0
        )
    if dilations[2] > 1:
        filters = np.insert(
            filters,
            [i for i in range(1, filters.shape[2])] * (dilations[2] - 1),
            values=0,
            axis=2
        )

    filter_shape = filters.shape[0:3]
    filter_shape = list(filter_shape)

    if data_format == "NCDHW":
        x = np.transpose(x, (0, 2, 3, 4, 1))

    x_shape = list(x.shape[1:4])
    if padding == "SAME":
        if x_shape[0] % strides[0] == 0:
            pad_d = max(filter_shape[0] - strides[0], 0)
        else:
            pad_d = max(filter_shape[0] - (x_shape[0] % strides[0]), 0)
        if x_shape[1] % strides[1] == 0:
            pad_h = max(filter_shape[1] - strides[1], 0)
        else:
            pad_h = max(filter_shape[1] - (x_shape[1] % strides[1]), 0)

        if x_shape[2] % strides[2] == 0:
            pad_w = max(filter_shape[2] - strides[2], 0)
        else:
            pad_w = max(filter_shape[2] - (x_shape[2] % strides[2]), 0)

        x = np.pad(
            x,
            [
                (0, 0),
                (pad_d // 2, pad_d - pad_d // 2),
                (pad_h // 2, pad_h - pad_h // 2),
                (pad_w // 2, pad_w - pad_w // 2),
                (0, 0),
            ],
            "constant",
        )

    x_shape = x.shape
    input_dim = filters.shape[-2]
    output_dim = filters.shape[-1]
    new_d = (x_shape[1] - filter_shape[0]) // strides[0] + 1
    new_h = (x_shape[2] - filter_shape[1]) // strides[1] + 1
    new_w = (x_shape[3] - filter_shape[2]) // strides[2] + 1
    new_shape = [x_shape[0], new_d, new_h, new_w] + filter_shape + [x_shape[-1]]
    new_strides = (
        x.strides[0],
        x.strides[1] * strides[2],
        x.strides[2] * strides[1],
        x.strides[3] * strides[0],
        x.strides[1],
        x.strides[2],
        x.strides[3],
        x.strides[4]
    )
    # B x OD X OH x OW x KH x KW x I
    sub_matrices = np.lib.stride_tricks.as_strided(
        x, new_shape, new_strides, writeable=False
    )
    # B x OD X OH x OW x KH x KW x I x O
    sub_matrices_w_output_dim = np.tile(
        np.expand_dims(sub_matrices, -1), [1] * 8 + [output_dim]
    )
    # B x OD X OH x OW x KH x KW x I x O
    mult = sub_matrices_w_output_dim * filters.reshape(
        [1] * 4 + filter_shape + [input_dim, output_dim]
    )
    # B x OD X OH x OW x O
    res = np.sum(mult, (4, 5, 6, 7))
    if data_format == "NCDHW":
        return np.transpose(res, (0, 4, 1, 2, 3))
    return res


def conv3d_transpose(*_):
    raise Exception("Convolutions not yet implemented for numpy library")
