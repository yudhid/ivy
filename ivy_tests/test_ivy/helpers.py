"""Collection of helpers for ivy unit tests."""

# global
import importlib
from contextlib import redirect_stdout
from io import StringIO
import sys
import re
import inspect
import numpy as np
import math
from typing import Union, List

TOLERANCE_DICT = {"float16": 1e-2, "float32": 1e-5, "float64": 1e-5, None: 1e-5}
cmd_line_args = (
    "as_variable",
    "native_array",
    "with_out",
    "container",
    "instance_method",
    "test_gradients"
)

try:
    import jax.numpy as jnp
except (ImportError, RuntimeError, AttributeError):
    jnp = None
try:
    import tensorflow as tf

    _tf_version = float(".".join(tf.__version__.split(".")[0:2]))
    if _tf_version >= 2.3:
        # noinspection PyPep8Naming,PyUnresolvedReferences
        from tensorflow.python.types.core import Tensor as tensor_type
    else:
        # noinspection PyPep8Naming
        # noinspection PyProtectedMember,PyUnresolvedReferences
        from tensorflow.python.framework.tensor_like import _TensorLike as tensor_type
    physical_devices = tf.config.list_physical_devices("GPU")
    for device in physical_devices:
        tf.config.experimental.set_memory_growth(device, True)
except ImportError:
    tf = None
try:
    import torch
except ImportError:
    torch = None
try:
    import mxnet as mx
    import mxnet.ndarray as mx_nd
except ImportError:
    mx = None
    mx_nd = None
from hypothesis import strategies as st
import hypothesis.extra.numpy as nph

# local
import ivy
import ivy.functional.backends.numpy as ivy_np


def get_ivy_numpy():
    try:
        import ivy.functional.backends.numpy
    except ImportError:
        return None
    return ivy.functional.backends.numpy


def get_ivy_jax():
    try:
        import ivy.functional.backends.jax
    except ImportError:
        return None
    return ivy.functional.backends.jax


def get_ivy_tensorflow():
    try:
        import ivy.functional.backends.tensorflow
    except ImportError:
        return None
    return ivy.functional.backends.tensorflow


def get_ivy_torch():
    try:
        import ivy.functional.backends.torch
    except ImportError:
        return None
    return ivy.functional.backends.torch


def get_ivy_mxnet():
    try:
        import ivy.functional.backends.mxnet
    except ImportError:
        return None
    return ivy.functional.backends.mxnet


_ivy_fws_dict = {
    "numpy": lambda: get_ivy_numpy(),
    "jax": lambda: get_ivy_jax(),
    "tensorflow": lambda: get_ivy_tensorflow(),
    "tensorflow_graph": lambda: get_ivy_tensorflow(),
    "torch": lambda: get_ivy_torch(),
    "mxnet": lambda: get_ivy_mxnet(),
}

_iterable_types = [list, tuple, dict]
_excluded = []


def _convert_vars(
    *, vars_in, from_type, to_type_callable=None, keep_other=True, to_type=None
):
    new_vars = list()
    for var in vars_in:
        if type(var) in _iterable_types:
            return_val = _convert_vars(
                vars_in=var, from_type=from_type, to_type_callable=to_type_callable
            )
            new_vars.append(return_val)
        elif isinstance(var, from_type):
            if isinstance(var, np.ndarray):
                if var.dtype == np.float64:
                    var = var.astype(np.float32)
                if bool(sum([stride < 0 for stride in var.strides])):
                    var = var.copy()
            if to_type_callable:
                new_vars.append(to_type_callable(var))
            else:
                raise Exception("Invalid. A conversion callable is required.")
        elif to_type is not None and isinstance(var, to_type):
            new_vars.append(var)
        elif keep_other:
            new_vars.append(var)

    return new_vars


def np_call(func, *args, **kwargs):
    ret = func(*args, **kwargs)
    if isinstance(ret, (list, tuple)):
        return ivy.to_native(ret, nested=True)
    return ivy.to_numpy(ret)


def jnp_call(func, *args, **kwargs):
    new_args = _convert_vars(
        vars_in=args, from_type=np.ndarray, to_type_callable=jnp.asarray
    )
    new_kw_vals = _convert_vars(
        vars_in=kwargs.values(), from_type=np.ndarray, to_type_callable=jnp.asarray
    )
    new_kwargs = dict(zip(kwargs.keys(), new_kw_vals))
    output = func(*new_args, **new_kwargs)
    if isinstance(output, tuple):
        return tuple(
            _convert_vars(
                vars_in=output,
                from_type=(jnp.ndarray, ivy.Array),
                to_type_callable=ivy.to_numpy,
            )
        )
    else:
        return _convert_vars(
            vars_in=[output],
            from_type=(jnp.ndarray, ivy.Array),
            to_type_callable=ivy.to_numpy,
        )[0]


def tf_call(func, *args, **kwargs):
    new_args = _convert_vars(
        vars_in=args, from_type=np.ndarray, to_type_callable=tf.convert_to_tensor
    )
    new_kw_vals = _convert_vars(
        vars_in=kwargs.values(),
        from_type=np.ndarray,
        to_type_callable=tf.convert_to_tensor,
    )
    new_kwargs = dict(zip(kwargs.keys(), new_kw_vals))
    output = func(*new_args, **new_kwargs)
    if isinstance(output, tuple):
        return tuple(
            _convert_vars(
                vars_in=output,
                from_type=(tensor_type, ivy.Array),
                to_type_callable=ivy.to_numpy,
            )
        )
    else:
        return _convert_vars(
            vars_in=[output],
            from_type=(tensor_type, ivy.Array),
            to_type_callable=ivy.to_numpy,
        )[0]


def tf_graph_call(func, *args, **kwargs):
    new_args = _convert_vars(
        vars_in=args, from_type=np.ndarray, to_type_callable=tf.convert_to_tensor
    )
    new_kw_vals = _convert_vars(
        vars_in=kwargs.values(),
        from_type=np.ndarray,
        to_type_callable=tf.convert_to_tensor,
    )
    new_kwargs = dict(zip(kwargs.keys(), new_kw_vals))

    @tf.function
    def tf_func(*local_args, **local_kwargs):
        return func(*local_args, **local_kwargs)

    output = tf_func(*new_args, **new_kwargs)

    if isinstance(output, tuple):
        return tuple(
            _convert_vars(
                vars_in=output,
                from_type=(tensor_type, ivy.Array),
                to_type_callable=ivy.to_numpy,
            )
        )
    else:
        return _convert_vars(
            vars_in=[output],
            from_type=(tensor_type, ivy.Array),
            to_type_callable=ivy.to_numpy,
        )[0]


def torch_call(func, *args, **kwargs):
    new_args = _convert_vars(
        vars_in=args, from_type=np.ndarray, to_type_callable=torch.from_numpy
    )
    new_kw_vals = _convert_vars(
        vars_in=kwargs.values(), from_type=np.ndarray, to_type_callable=torch.from_numpy
    )
    new_kwargs = dict(zip(kwargs.keys(), new_kw_vals))
    output = func(*new_args, **new_kwargs)
    if isinstance(output, tuple):
        return tuple(
            _convert_vars(
                vars_in=output,
                from_type=(torch.Tensor, ivy.Array),
                to_type_callable=ivy.to_numpy,
            )
        )
    else:
        return _convert_vars(
            vars_in=[output],
            from_type=(torch.Tensor, ivy.Array),
            to_type_callable=ivy.to_numpy,
        )[0]


def mx_call(func, *args, **kwargs):
    new_args = _convert_vars(
        vars_in=args, from_type=np.ndarray, to_type_callable=mx_nd.array
    )
    new_kw_items = _convert_vars(
        vars_in=kwargs.values(), from_type=np.ndarray, to_type_callable=mx_nd.array
    )
    new_kwargs = dict(zip(kwargs.keys(), new_kw_items))
    output = func(*new_args, **new_kwargs)
    if isinstance(output, tuple):
        return tuple(
            _convert_vars(
                vars_in=output,
                from_type=(mx_nd.ndarray.NDArray, ivy.Array),
                to_type_callable=ivy.to_numpy,
            )
        )
    else:
        return _convert_vars(
            vars_in=[output],
            from_type=(mx_nd.ndarray.NDArray, ivy.Array),
            to_type_callable=ivy.to_numpy,
        )[0]


_calls = [np_call, jnp_call, tf_call, tf_graph_call, torch_call, mx_call]


def assert_compilable(fn):
    try:
        ivy.compile(fn)
    except Exception as e:
        raise e


# function that trims white spaces from docstrings
def trim(*, docstring):
    """Trim function from PEP-257"""
    if not docstring:
        return ""
    # Convert tabs to spaces (following the normal Python rules)
    # and split into a list of lines:
    lines = docstring.expandtabs().splitlines()
    # Determine minimum indentation (first line doesn't count):
    indent = sys.maxsize
    for line in lines[1:]:
        stripped = line.lstrip()
        if stripped:
            indent = min(indent, len(line) - len(stripped))
    # Remove indentation (first line is special):
    trimmed = [lines[0].strip()]
    if indent < sys.maxsize:
        for line in lines[1:]:
            trimmed.append(line[indent:].rstrip())
    # Strip off trailing and leading blank lines:
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    while trimmed and not trimmed[0]:
        trimmed.pop(0)

    # Current code/unittests expects a line return at
    # end of multiline docstrings
    # workaround expected behavior from unittests
    if "\n" in docstring:
        trimmed.append("")

    # Return a single string:
    return "\n".join(trimmed)


def docstring_examples_run(*, fn, from_container=False, from_array=False):
    if not hasattr(fn, "__name__"):
        return True
    fn_name = fn.__name__
    if fn_name not in ivy.backend_handler.ivy_original_dict:
        return True

    if from_container:
        docstring = getattr(
            ivy.backend_handler.ivy_original_dict["Container"], fn_name
        ).__doc__
    elif from_array:
        docstring = getattr(
            ivy.backend_handler.ivy_original_dict["Array"], fn_name
        ).__doc__
    else:
        docstring = ivy.backend_handler.ivy_original_dict[fn_name].__doc__

    if docstring is None:
        return True

    # removing extra new lines and trailing white spaces from the docstrings
    trimmed_docstring = trim(docstring=docstring)
    trimmed_docstring = trimmed_docstring.split("\n")

    # end_index: -1, if print statement is not found in the docstring
    end_index = -1

    # parsed_output is set as an empty string to manage functions with multiple inputs
    parsed_output = ""

    # parsing through the docstrings to find lines with print statement
    # following which is our parsed output
    sub = ">>> print("
    for index, line in enumerate(trimmed_docstring):
        if sub in line:
            end_index = trimmed_docstring.index("", index)
            p_output = trimmed_docstring[index + 1 : end_index]
            p_output = ("").join(p_output).replace(" ", "")
            parsed_output += p_output

    if end_index == -1:
        return True

    executable_lines = [
        line.split(">>>")[1][1:] for line in docstring.split("\n") if ">>>" in line
    ]

    # noinspection PyBroadException
    f = StringIO()
    with redirect_stdout(f):
        for line in executable_lines:
            # noinspection PyBroadException
            try:
                exec(line)
            except Exception as e:
                print(e, " ", ivy.current_backend_str(), " ", line)

    output = f.getvalue()
    output = output.rstrip()
    output = output.replace(" ", "").replace("\n", "")

    # handling cases when the stdout contains ANSI colour codes
    # 7-bit C1 ANSI sequences
    ansi_escape = re.compile(
        r"""
    \x1B  # ESC
    (?:   # 7-bit C1 Fe (except CSI)
        [@-Z\\-_]
    |     # or [ for CSI, followed by a control sequence
        \[
        [0-?]*  # Parameter bytes
        [ -/]*  # Intermediate bytes
        [@-~]   # Final byte
    )
    """,
        re.VERBOSE,
    )

    output = ansi_escape.sub("", output)

    # print("Output: ", output)
    # print("Putput: ", parsed_output)

    # assert output == parsed_output, "Output is unequal to the docstrings output."
    if not (output == parsed_output):
        print(
            "output for ",
            fn_name,
            " on run: ",
            output,
            "\noutput in docs :",
            parsed_output,
        )
        ivy.warn(
            "Output is unequal to the docstrings output: %s" % fn_name, stacklevel=0
        )
        return False
    return True


def var_fn(x, *, dtype=None, device=None):
    return ivy.variable(ivy.array(x, dtype=dtype, device=device))


def exclude(*, exclusion_list):
    global _excluded
    _excluded += list(set(exclusion_list) - set(_excluded))


def frameworks():
    return list(
        set(
            [
                ivy_fw()
                for fw_str, ivy_fw in _ivy_fws_dict.items()
                if ivy_fw() is not None and fw_str not in _excluded
            ]
        )
    )


def calls():
    return [
        call
        for (fw_str, ivy_fw), call in zip(_ivy_fws_dict.items(), _calls)
        if ivy_fw() is not None and fw_str not in _excluded
    ]


def f_n_calls():
    return [
        (ivy_fw(), call)
        for (fw_str, ivy_fw), call in zip(_ivy_fws_dict.items(), _calls)
        if ivy_fw() is not None and fw_str not in _excluded
    ]


def assert_all_close(ret_np, ret_from_np, rtol=1e-05, atol=1e-08):
    assert ret_np.dtype is ret_from_np.dtype, (
        "the return with a NumPy backend produced data type of {}, "
        "while the return with a {} backend returned a data type of {}.".format(
            ret_from_np.dtype, ivy.current_backend_str(), ret_np.dtype
        )
    )
    if ivy.is_ivy_container(ret_np) and ivy.is_ivy_container(ret_from_np):
        ivy.Container.multi_map(assert_all_close, [ret_np, ret_from_np])
    else:
        assert np.allclose(
            np.nan_to_num(ret_np), np.nan_to_num(ret_from_np), rtol=rtol, atol=atol
        ), "{} != {}".format(ret_np, ret_from_np)


def kwargs_to_args_n_kwargs(*, num_positional_args, kwargs):
    args = [v for v in list(kwargs.values())[:num_positional_args]]
    kwargs = {k: kwargs[k] for k in list(kwargs.keys())[num_positional_args:]}
    return args, kwargs


def list_of_length(*, x, length):
    return st.lists(x, min_size=length, max_size=length)


def as_cont(*, x):
    return ivy.Container({"a": x, "b": {"c": x, "d": x}})


def as_lists(*args):
    return (a if isinstance(a, list) else [a] for a in args)


def flatten(*, ret):
    # flatten the return
    if not isinstance(ret, tuple):
        ret = (ret,)

    ret_idxs = ivy.nested_indices_where(ret, ivy.is_ivy_array)
    ret_flat = ivy.multi_index_nest(ret, ret_idxs)

    # convert the return to NumPy
    ret_np_flat = [ivy.to_numpy(x) for x in ret_flat]
    return ret_np_flat


def get_ret_and_flattened_array(func, *args, **kwargs):
    ret = func(*args, **kwargs)
    return ret, flatten(ret=ret)


def value_test(*, ret_np_flat, ret_from_np_flat, rtol=None, atol=1e-6):
    if type(ret_np_flat) != list:
        ret_np_flat = [ret_np_flat]
    if type(ret_from_np_flat) != list:
        ret_from_np_flat = [ret_from_np_flat]
    assert len(ret_np_flat) == len(ret_from_np_flat)
    # value tests, iterating through each array in the flattened returns
    if not rtol:
        for ret_np, ret_from_np in zip(ret_np_flat, ret_from_np_flat):
            rtol = TOLERANCE_DICT.get(str(ret_from_np.dtype), 1e-03)
            assert_all_close(ret_np, ret_from_np, rtol=rtol, atol=atol)
    else:
        for ret_np, ret_from_np in zip(ret_np_flat, ret_from_np_flat):
            assert_all_close(ret_np, ret_from_np, rtol=rtol, atol=atol)


def args_to_container(array_args):
    array_args_container = ivy.Container({str(k): v for k, v in enumerate(array_args)})
    return array_args_container


def gradient_test(
    *,
    fn_name,
    all_as_kwargs_np,
    args_np,
    kwargs_np,
    input_dtypes,
    as_variable_flags,
    native_array_flags,
    container_flags,
    rtol_: float = None,
    atol_: float = 1e-06,
    ground_truth_backend: str = "torch",
):
    def grad_fn(xs):
        array_vals = [v for k, v in xs.to_iterator()]
        arg_array_vals = array_vals[0 : len(args_idxs)]
        kwarg_array_vals = array_vals[len(args_idxs) :]
        args_writeable = ivy.copy_nest(args)
        kwargs_writeable = ivy.copy_nest(kwargs)
        ivy.set_nest_at_indices(args_writeable, args_idxs, arg_array_vals)
        ivy.set_nest_at_indices(kwargs_writeable, kwargs_idxs, kwarg_array_vals)
        return ivy.mean(ivy.__dict__[fn_name](*args_writeable, **kwargs_writeable))

    args, kwargs, _, args_idxs, kwargs_idxs = create_args_kwargs(
        args_np=args_np,
        kwargs_np=kwargs_np,
        input_dtypes=input_dtypes,
        as_variable_flags=as_variable_flags,
        native_array_flags=native_array_flags,
        container_flags=container_flags,
    )
    arg_array_vals = list(ivy.multi_index_nest(args, args_idxs))
    kwarg_array_vals = list(ivy.multi_index_nest(kwargs, kwargs_idxs))
    xs = args_to_container(arg_array_vals + kwarg_array_vals)
    _, ret_np_flat = get_ret_and_flattened_array(
        ivy.execute_with_gradients, grad_fn, xs
    )
    grads_np_flat = ret_np_flat[1]
    # compute the return with a Ground Truth backend
    ivy.set_backend(ground_truth_backend)
    test_unsupported = check_unsupported_dtype(
        fn=ivy.__dict__[fn_name],
        input_dtypes=input_dtypes,
        all_as_kwargs_np=all_as_kwargs_np,
    )
    if test_unsupported:
        return
    args, kwargs, _, args_idxs, kwargs_idxs = create_args_kwargs(
        args_np=args_np,
        kwargs_np=kwargs_np,
        input_dtypes=input_dtypes,
        as_variable_flags=as_variable_flags,
        native_array_flags=native_array_flags,
        container_flags=container_flags,
    )
    arg_array_vals = list(ivy.multi_index_nest(args, args_idxs))
    kwarg_array_vals = list(ivy.multi_index_nest(kwargs, kwargs_idxs))
    xs = args_to_container(arg_array_vals + kwarg_array_vals)
    _, ret_np_from_gt_flat = get_ret_and_flattened_array(
        ivy.execute_with_gradients, grad_fn, xs
    )
    grads_np_from_gt_flat = ret_np_from_gt_flat[1]
    ivy.unset_backend()
    # value test
    value_test(
        ret_np_flat=grads_np_flat,
        ret_from_np_flat=grads_np_from_gt_flat,
        rtol=rtol_,
        atol=atol_,
    )


def check_unsupported_dtype(*, fn, input_dtypes, all_as_kwargs_np):
    # check for unsupported dtypes
    test_unsupported = False
    unsupported_dtypes_fn = ivy.function_unsupported_dtypes(fn)
    supported_dtypes_fn = ivy.function_supported_dtypes(fn)
    if unsupported_dtypes_fn:
        for d in input_dtypes:
            if d in unsupported_dtypes_fn:
                test_unsupported = True
                break
        if (
            "dtype" in all_as_kwargs_np
            and all_as_kwargs_np["dtype"] in unsupported_dtypes_fn
        ):
            test_unsupported = True
    if supported_dtypes_fn and not test_unsupported:
        for d in input_dtypes:
            if d not in supported_dtypes_fn:
                test_unsupported = True
                break
        if (
            "dtype" in all_as_kwargs_np
            and all_as_kwargs_np["dtype"] not in supported_dtypes_fn
        ):
            test_unsupported = True
    return test_unsupported


def check_unsupported_device(*, fn, input_device, all_as_kwargs_np):
    # check for unsupported dtypes
    test_unsupported = False
    unsupported_devices_fn = ivy.function_unsupported_devices(fn)
    supported_devices_fn = ivy.function_supported_devices(fn)
    if unsupported_devices_fn:
        if input_device in unsupported_devices_fn:
            test_unsupported = True
        if (
            "device" in all_as_kwargs_np
            and all_as_kwargs_np["device"] in unsupported_devices_fn
        ):
            test_unsupported = True
    if supported_devices_fn and not test_unsupported:
        if input_device not in supported_devices_fn:
            test_unsupported = True
        if (
            "device" in all_as_kwargs_np
            and all_as_kwargs_np["device"] not in supported_devices_fn
        ):
            test_unsupported = True
    return test_unsupported


def check_unsupported_device_and_dtype(*, fn, device, input_dtypes, all_as_kwargs_np):
    # check for unsupported dtypes
    test_unsupported = False
    unsupported_devices_dtypes_fn = ivy.function_unsupported_devices_and_dtypes(fn)
    supported_devices_dtypes_fn = ivy.function_supported_devices_and_dtypes(fn)
    for i in range(len(unsupported_devices_dtypes_fn["devices"])):
        if device in unsupported_devices_dtypes_fn["devices"][i]:
            for d in input_dtypes:
                if d in unsupported_devices_dtypes_fn["dtypes"][i]:
                    test_unsupported = True
                    break
    if (
        "device" in all_as_kwargs_np
        and "dtype" in all_as_kwargs_np
        and all_as_kwargs_np["device"] in unsupported_devices_dtypes_fn["devices"]
    ):
        index = unsupported_devices_dtypes_fn["devices"].index(
            all_as_kwargs_np["device"]
        )
        if all_as_kwargs_np["dtype"] in unsupported_devices_dtypes_fn["dtypes"][index]:
            test_unsupported = True
    if test_unsupported:
        return test_unsupported

    for i in range(len(supported_devices_dtypes_fn["devices"])):
        if device in supported_devices_dtypes_fn["devices"][i]:
            for d in input_dtypes:
                if d not in supported_devices_dtypes_fn["dtypes"][i]:
                    test_unsupported = True
                    break
        else:
            test_unsupported = True
        if (
            "device" in all_as_kwargs_np
            and "dtype" in all_as_kwargs_np
            and all_as_kwargs_np["device"] in supported_devices_dtypes_fn["devices"]
        ):
            if all_as_kwargs_np["device"] not in supported_devices_dtypes_fn["devices"]:
                test_unsupported = True
            else:
                index = supported_devices_dtypes_fn["devices"].index(
                    all_as_kwargs_np["device"]
                )
                if (
                    all_as_kwargs_np["dtype"]
                    not in supported_devices_dtypes_fn["dtypes"][index]
                ):
                    test_unsupported = True
    return test_unsupported


def create_args_kwargs(
    *,
    args_np,
    kwargs_np,
    input_dtypes,
    as_variable_flags,
    native_array_flags=None,
    container_flags=None,
):

    # extract all arrays from the arguments and keyword arguments
    args_idxs = ivy.nested_indices_where(args_np, lambda x: isinstance(x, np.ndarray))
    arg_np_vals = ivy.multi_index_nest(args_np, args_idxs)
    kwargs_idxs = ivy.nested_indices_where(
        kwargs_np, lambda x: isinstance(x, np.ndarray)
    )
    kwarg_np_vals = ivy.multi_index_nest(kwargs_np, kwargs_idxs)

    # assert that the number of arrays aligns with the dtypes and as_variable_flags
    num_arrays = len(arg_np_vals) + len(kwarg_np_vals)
    if num_arrays > 0:
        assert num_arrays == len(input_dtypes), (
            "Found {} arrays in the input arguments, but {} dtypes and "
            "as_variable_flags. Make sure to pass in a sequence of bools for all "
            "associated boolean flag inputs to test_function, with the sequence length "
            "being equal to the number of arrays in the arguments.".format(
                num_arrays, len(input_dtypes)
            )
        )

    # create args
    num_arg_vals = len(arg_np_vals)
    arg_array_vals = [
        ivy.array(x, dtype=d) for x, d in zip(arg_np_vals, input_dtypes[:num_arg_vals])
    ]
    arg_array_vals = [
        ivy.variable(x) if v else x
        for x, v in zip(arg_array_vals, as_variable_flags[:num_arg_vals])
    ]
    if native_array_flags:
        arg_array_vals = [
            ivy.to_native(x) if n else x
            for x, n in zip(arg_array_vals, native_array_flags[:num_arg_vals])
        ]
    if container_flags:
        arg_array_vals = [
            as_cont(x=x) if c else x
            for x, c in zip(arg_array_vals, container_flags[:num_arg_vals])
        ]
    args = ivy.copy_nest(args_np, to_mutable=True)
    ivy.set_nest_at_indices(args, args_idxs, arg_array_vals)

    # create kwargs
    kwarg_array_vals = [
        ivy.array(x, dtype=d)
        for x, d in zip(kwarg_np_vals, input_dtypes[num_arg_vals:])
    ]
    kwarg_array_vals = [
        ivy.variable(x) if v else x
        for x, v in zip(kwarg_array_vals, as_variable_flags[num_arg_vals:])
    ]
    if native_array_flags:
        kwarg_array_vals = [
            ivy.to_native(x) if n else x
            for x, n in zip(kwarg_array_vals, native_array_flags[num_arg_vals:])
        ]
    if container_flags:
        kwarg_array_vals = [
            as_cont(x=x) if c else x
            for x, c in zip(kwarg_array_vals, container_flags[num_arg_vals:])
        ]
    kwargs = ivy.copy_nest(kwargs_np, to_mutable=True)
    ivy.set_nest_at_indices(kwargs, kwargs_idxs, kwarg_array_vals)
    return args, kwargs, num_arg_vals, args_idxs, kwargs_idxs


def test_unsupported_function(*, fn, args, kwargs):
    try:
        fn(*args, **kwargs)
        assert False
    except:  # noqa
        return


def test_method(
    *,
    input_dtypes: Union[ivy.Dtype, List[ivy.Dtype]],
    as_variable_flags: Union[bool, List[bool]],
    all_as_kwargs_np,
    num_positional_args: int,
    input_dtypes_constructor: Union[ivy.Dtype, List[ivy.Dtype]],
    as_variable_flags_constructor: Union[bool, List[bool]],
    constructor_kwargs,
    num_positional_args_constructor: int,
    fw: str,
    class_name: str,
    rtol: float = None,
    atol: float = 1e-06,
    test_values: bool = True,
    ground_truth_backend: str = "numpy",
):
    """Tests a class-method that consumes (or returns) arrays for the current backend
    by comparing the result with numpy.

    Parameters
    ----------
    input_dtypes
        data types of the input arguments in order.
    as_variable_flags
        dictates whether the corresponding input argument should be treated as an
        ivy Variable.
    all_as_kwargs_np:
        input arguments to the function as keyword arguments.
    num_positional_args
        number of input arguments that must be passed as positional
        arguments.
    input_dtypes_constructor
        data types of the input arguments for the constructor in order.
    as_variable_flags_constructor
        dictates whether the corresponding input argument should be treated as an
        ivy Variable for the constructor
    constructor_kwargs:
        input arguments to the constructor as keyword arguments.
    num_positional_args_constructor
        number of input arguments that must be passed as positional
        arguments to the constructor.
    fw
        current backend (framework).
    class_name
        name of the class to test.
    rtol
        relative tolerance value.
    atol
        absolute tolerance value.
    test_values
        if True, test for the correctness of the resulting values.
    ground_truth_backend
        Ground Truth Backend to compare the result-values.

    Returns
    -------
    ret
        optional, return value from the function
    ret_gt
        optional, return value from the Ground Truth function
    """
    # convert single values to length 1 lists
    input_dtypes, as_variable_flags = as_lists(input_dtypes, as_variable_flags)
    # update variable flags to be compatible with float dtype
    as_variable_flags = [
        v if ivy.is_float_dtype(d) else False
        for v, d in zip(as_variable_flags, input_dtypes)
    ]

    # change all data types so that they are supported by this framework
    input_dtypes = ["float32" if d in ivy.invalid_dtypes else d for d in input_dtypes]

    # create args
    calling_args_np, calling_kwargs_np = kwargs_to_args_n_kwargs(
        num_positional_args=num_positional_args, kwargs=all_as_kwargs_np
    )
    calling_args, calling_kwargs, _, _, _ = create_args_kwargs(
        args_np=calling_args_np,
        kwargs_np=calling_kwargs_np,
        input_dtypes=input_dtypes,
        as_variable_flags=as_variable_flags,
    )

    constructor_args_np, constructor_kwargs_np = kwargs_to_args_n_kwargs(
        num_positional_args=num_positional_args_constructor, kwargs=constructor_kwargs
    )
    constructor_args, constructor_kwargs, _, _, _ = create_args_kwargs(
        args_np=constructor_args_np,
        kwargs_np=constructor_kwargs_np,
        input_dtypes=input_dtypes_constructor,
        as_variable_flags=as_variable_flags_constructor,
    )
    # run
    ins = ivy.__dict__[class_name](*constructor_args, **constructor_kwargs)
    ret, ret_np_flat = get_ret_and_flattened_array(ins, *calling_args, **calling_kwargs)
    # compute the return with a Ground Truth backend
    ivy.set_backend(ground_truth_backend)
    calling_args_gt, calling_kwargs_gt, _, _, _ = create_args_kwargs(
        args_np=calling_args_np,
        kwargs_np=calling_kwargs_np,
        input_dtypes=input_dtypes,
        as_variable_flags=as_variable_flags,
    )
    constructor_args_gt, constructor_kwargs_gt, _, _, _ = create_args_kwargs(
        args_np=constructor_args_np,
        kwargs_np=constructor_kwargs_np,
        input_dtypes=input_dtypes_constructor,
        as_variable_flags=as_variable_flags_constructor,
    )
    ins_gt = ivy.__dict__[class_name](*constructor_args_gt, **constructor_kwargs_gt)
    ret_from_gt, ret_np_from_gt_flat = get_ret_and_flattened_array(
        ins_gt, *calling_args_gt, **calling_kwargs_gt
    )
    ivy.unset_backend()
    # assuming value test will be handled manually in the test function
    if not test_values:
        return ret, ret_from_gt
    # value test
    value_test(
        ret_np_flat=ret_np_flat,
        ret_from_np_flat=ret_np_from_gt_flat,
        rtol=rtol,
        atol=atol,
    )


def test_function(
    *,
    input_dtypes: Union[ivy.Dtype, List[ivy.Dtype]],
    as_variable_flags: Union[bool, List[bool]],
    with_out: bool,
    num_positional_args: int,
    native_array_flags: Union[bool, List[bool]],
    container_flags: Union[bool, List[bool]],
    instance_method: bool,
    fw: str,
    fn_name: str,
    rtol_: float = None,
    atol_: float = 1e-06,
    test_values: bool = True,
    test_gradients: bool = False,
    ground_truth_backend: str = "numpy",
    device_: str = "cpu",
    **all_as_kwargs_np,
):
    """Tests a function that consumes (or returns) arrays for the current backend
    by comparing the result with numpy.

    Parameters
    ----------
    input_dtypes
        data types of the input arguments in order.
    as_variable_flags
        dictates whether the corresponding input argument should be treated
        as an ivy Variable.
    with_out
        if True, the function is also tested with the optional out argument.
    num_positional_args
        number of input arguments that must be passed as positional
        arguments.
    native_array_flags
        dictates whether the corresponding input argument should be treated
         as a native array.
    container_flags
        dictates whether the corresponding input argument should be treated
         as an ivy Container.
    instance_method
        if True, the function is run as an instance method of the first
         argument (should be an ivy Array or Container).
    fw
        current backend (framework).
    fn_name
        name of the function to test.
    rtol_
        relative tolerance value.
    atol_
        absolute tolerance value.
    test_values
        if True, test for the correctness of the resulting values.
    test_gradients
        if True, test for the correctness of gradients.
    ground_truth_backend
        Ground Truth Backend to compare the result-values.
    all_as_kwargs_np
        input arguments to the function as keyword arguments.

    Returns
    -------
    ret
        optional, return value from the function
    ret_gt
        optional, return value from the Ground Truth function

    Examples
    --------
    >>> input_dtypes = 'float64'
    >>> as_variable_flags = False
    >>> with_out = False
    >>> num_positional_args = 0
    >>> native_array_flags = False
    >>> container_flags = False
    >>> instance_method = False
    >>> fw = "torch"
    >>> fn_name = "abs"
    >>> x = np.array([-1])
    >>> test_function(input_dtypes, as_variable_flags, with_out,\
                            num_positional_args, native_array_flags,\
                            container_flags, instance_method, fw, fn_name, x=x)

    >>> input_dtypes = ['float64', 'float32']
    >>> as_variable_flags = [False, True]
    >>> with_out = False
    >>> num_positional_args = 1
    >>> native_array_flags = [True, False]
    >>> container_flags = [False, False]
    >>> instance_method = False
    >>> fw = "numpy"
    >>> fn_name = "add"
    >>> x1 = np.array([1, 3, 4])
    >>> x2 = np.array([-3, 15, 24])
    >>> test_function(input_dtypes, as_variable_flags, with_out,\
                            num_positional_args, native_array_flags,\
                             container_flags, instance_method,\
                              fw, fn_name, x1=x1, x2=x2)
    """
    # convert single values to length 1 lists
    input_dtypes, as_variable_flags, native_array_flags, container_flags = as_lists(
        input_dtypes, as_variable_flags, native_array_flags, container_flags
    )

    # make all lists equal in length
    num_arrays = max(
        len(input_dtypes),
        len(as_variable_flags),
        len(native_array_flags),
        len(container_flags),
    )
    if len(input_dtypes) < num_arrays:
        input_dtypes = [input_dtypes[0] for _ in range(num_arrays)]
    if len(as_variable_flags) < num_arrays:
        as_variable_flags = [as_variable_flags[0] for _ in range(num_arrays)]
    if len(native_array_flags) < num_arrays:
        native_array_flags = [native_array_flags[0] for _ in range(num_arrays)]
    if len(container_flags) < num_arrays:
        container_flags = [container_flags[0] for _ in range(num_arrays)]

    # update variable flags to be compatible with float dtype and with_out args
    as_variable_flags = [
        v if ivy.is_float_dtype(d) and not with_out else False
        for v, d in zip(as_variable_flags, input_dtypes)
    ]

    # update instance_method flag to only be considered if the
    # first term is either an ivy.Array or ivy.Container
    instance_method = instance_method and (
        not native_array_flags[0] or container_flags[0]
    )

    # split the arguments into their positional and keyword components
    args_np, kwargs_np = kwargs_to_args_n_kwargs(
        num_positional_args=num_positional_args, kwargs=all_as_kwargs_np
    )

    fn = getattr(ivy, fn_name)
    test_unsupported = check_unsupported_dtype(
        fn=fn, input_dtypes=input_dtypes, all_as_kwargs_np=all_as_kwargs_np
    )
    if not test_unsupported:
        test_unsupported = check_unsupported_device(
            fn=fn, input_device=device_, all_as_kwargs_np=all_as_kwargs_np
        )
    if not test_unsupported:
        test_unsupported = check_unsupported_device_and_dtype(
            fn=fn,
            device=device_,
            input_dtypes=input_dtypes,
            all_as_kwargs_np=all_as_kwargs_np,
        )
    if test_unsupported:
        try:
            args, kwargs, num_arg_vals, args_idxs, kwargs_idxs = create_args_kwargs(
                args_np=args_np,
                kwargs_np=kwargs_np,
                input_dtypes=input_dtypes,
                as_variable_flags=as_variable_flags,
                native_array_flags=native_array_flags,
                container_flags=container_flags,
            )
        except Exception:
            return
    else:
        args, kwargs, num_arg_vals, args_idxs, kwargs_idxs = create_args_kwargs(
            args_np=args_np,
            kwargs_np=kwargs_np,
            input_dtypes=input_dtypes,
            as_variable_flags=as_variable_flags,
            native_array_flags=native_array_flags,
            container_flags=container_flags,
        )

    # run either as an instance method or from the API directly
    instance = None
    if instance_method:
        is_instance = [
            (not n) or c for n, c in zip(native_array_flags, container_flags)
        ]
        arg_is_instance = is_instance[:num_arg_vals]
        kwarg_is_instance = is_instance[num_arg_vals:]
        if arg_is_instance and max(arg_is_instance):
            i = 0
            for i, a in enumerate(arg_is_instance):
                if a:
                    break
            instance_idx = args_idxs[i]
            instance = ivy.index_nest(args, instance_idx)
            args = ivy.copy_nest(args, to_mutable=True)
            ivy.prune_nest_at_index(args, instance_idx)
        else:
            i = 0
            for i, a in enumerate(kwarg_is_instance):
                if a:
                    break
            instance_idx = kwargs_idxs[i]
            instance = ivy.index_nest(kwargs, instance_idx)
            kwargs = ivy.copy_nest(kwargs, to_mutable=True)
            ivy.prune_nest_at_index(kwargs, instance_idx)
        if test_unsupported:
            test_unsupported_function(
                fn=instance.__getattribute__(fn_name), args=args, kwargs=kwargs
            )
            return

        ret, ret_np_flat = get_ret_and_flattened_array(
            instance.__getattribute__(fn_name), *args, **kwargs
        )
    else:
        if test_unsupported:
            test_unsupported_function(
                fn=ivy.__dict__[fn_name], args=args, kwargs=kwargs
            )
            return
        ret, ret_np_flat = get_ret_and_flattened_array(
            ivy.__dict__[fn_name], *args, **kwargs
        )
    # assert idx of return if the idx of the out array provided
    if with_out:
        out = ivy.zeros_like(ret)
        assert not isinstance(ret, tuple)
        if max(container_flags):
            assert ivy.is_ivy_container(ret)
        else:
            assert ivy.is_array(ret)
        if instance_method:
            ret, ret_np_flat = get_ret_and_flattened_array(
                instance.__getattribute__(fn_name), *args, **kwargs, out=out
            )
        else:
            ret, ret_np_flat = get_ret_and_flattened_array(
                ivy.__dict__[fn_name], *args, **kwargs, out=out
            )
        assert ret is out
        if not max(container_flags) and ivy.native_inplace_support:
            # these backends do not always support native inplace updates
            assert ret.data is out.data
    # compute the return with a Ground Truth backend
    ivy.set_backend(ground_truth_backend)
    try:
        fn = getattr(ivy, fn_name)
        test_unsupported = check_unsupported_dtype(
            fn=fn, input_dtypes=input_dtypes, all_as_kwargs_np=all_as_kwargs_np
        )
        # create args
        if test_unsupported:
            try:
                args, kwargs, _, _, _ = create_args_kwargs(
                    args_np=args_np,
                    kwargs_np=kwargs_np,
                    input_dtypes=input_dtypes,
                    as_variable_flags=as_variable_flags,
                    native_array_flags=native_array_flags,
                    container_flags=container_flags,
                )
            except Exception:
                ivy.unset_backend()
                return
        else:
            args, kwargs, _, _, _ = create_args_kwargs(
                args_np=args_np,
                kwargs_np=kwargs_np,
                input_dtypes=input_dtypes,
                as_variable_flags=as_variable_flags,
                native_array_flags=native_array_flags,
                container_flags=container_flags,
            )
        if test_unsupported:
            test_unsupported_function(
                fn=ivy.__dict__[fn_name], args=args, kwargs=kwargs
            )
            ivy.unset_backend()
            return
        ret_from_gt, ret_np_from_gt_flat = get_ret_and_flattened_array(
            ivy.__dict__[fn_name], *args, **kwargs
        )
    except Exception as e:
        ivy.unset_backend()
        raise e
    ivy.unset_backend()
    # gradient test
    if (
        test_gradients
        and not fw == "numpy"
        and all(as_variable_flags)
        and not any(container_flags)
        and not instance_method
    ):
        gradient_test(
            fn_name=fn_name,
            all_as_kwargs_np=all_as_kwargs_np,
            args_np=args_np,
            kwargs_np=kwargs_np,
            input_dtypes=input_dtypes,
            as_variable_flags=as_variable_flags,
            native_array_flags=native_array_flags,
            container_flags=container_flags,
            rtol_=rtol_,
            atol_=atol_,
        )

    # assuming value test will be handled manually in the test function
    if not test_values:
        return ret, ret_from_gt
    # value test
    value_test(
        ret_np_flat=ret_np_flat,
        ret_from_np_flat=ret_np_from_gt_flat,
        rtol=rtol_,
        atol=atol_,
    )


def test_frontend_function(
    *,
    input_dtypes: Union[ivy.Dtype, List[ivy.Dtype]],
    as_variable_flags: Union[bool, List[bool]],
    with_out: bool,
    num_positional_args: int,
    native_array_flags: Union[bool, List[bool]],
    fw: str,
    frontend: str,
    fn_name: str,
    rtol: float = None,
    atol: float = 1e-06,
    test_values: bool = True,
    **all_as_kwargs_np,
):
    """Tests a frontend function for the current backend by comparing the result with
    the function in the associated framework.

    Parameters
    ----------
    input_dtypes
        data types of the input arguments in order.
    as_variable_flags
        dictates whether the corresponding input argument should be treated
        as an ivy Variable.
    with_out
        if True, the function is also tested with the optional out argument.
    num_positional_args
        number of input arguments that must be passed as positional
        arguments.
    native_array_flags
        dictates whether the corresponding input argument should be treated
        as a native array.
    fw
        current backend (framework).
    frontend
        current frontend (framework).
    fn_name
        name of the function to test.
    rtol
        relative tolerance value.
    atol
        absolute tolerance value.
    test_values
        if True, test for the correctness of the resulting values.
    all_as_kwargs_np
        input arguments to the function as keyword arguments.

    Returns
    -------
    ret
        optional, return value from the function
    ret_np
        optional, return value from the Numpy function
    """
    # convert single values to length 1 lists
    input_dtypes, as_variable_flags, native_array_flags = as_lists(
        input_dtypes, as_variable_flags, native_array_flags
    )

    # update variable flags to be compatible with float dtype and with_out args
    as_variable_flags = [
        v if ivy.is_float_dtype(d) and not with_out else False
        for v, d in zip(as_variable_flags, input_dtypes)
    ]

    # parse function name and frontend submodules (i.e. jax.lax, jax.numpy etc.)
    *frontend_submods, fn_name = fn_name.split(".")

    # check for unsupported dtypes in backend framework
    function = getattr(ivy.functional.frontends.__dict__[frontend], fn_name)
    test_unsupported = check_unsupported_dtype(
        fn=function, input_dtypes=input_dtypes, all_as_kwargs_np=all_as_kwargs_np
    )

    # split the arguments into their positional and keyword components
    args_np, kwargs_np = kwargs_to_args_n_kwargs(
        num_positional_args=num_positional_args, kwargs=all_as_kwargs_np
    )

    # change all data types so that they are supported by this framework
    input_dtypes = ["float32" if d in ivy.invalid_dtypes else d for d in input_dtypes]

    # create args
    if test_unsupported:
        try:
            args, kwargs, num_arg_vals, args_idxs, kwargs_idxs = create_args_kwargs(
                args_np=args_np,
                kwargs_np=kwargs_np,
                input_dtypes=input_dtypes,
                as_variable_flags=as_variable_flags,
                native_array_flags=native_array_flags,
            )
            args_ivy, kwargs_ivy = ivy.args_to_ivy(*args, **kwargs)
        except Exception:
            return
    else:
        args, kwargs, num_arg_vals, args_idxs, kwargs_idxs = create_args_kwargs(
            args_np=args_np,
            kwargs_np=kwargs_np,
            input_dtypes=input_dtypes,
            as_variable_flags=as_variable_flags,
            native_array_flags=native_array_flags,
        )
        args_ivy, kwargs_ivy = ivy.args_to_ivy(*args, **kwargs)

    # frontend function
    frontend_fn = ivy.functional.frontends.__dict__[frontend].__dict__[fn_name]

    # run from the Ivy API directly
    if test_unsupported:
        test_unsupported_function(fn=frontend_fn, args=args, kwargs=kwargs)
        return
    ret = frontend_fn(*args, **kwargs)

    # assert idx of return if the idx of the out array provided
    out = ret
    if with_out:
        assert not isinstance(ret, tuple)
        assert ivy.is_array(ret)
        if "out" in kwargs:
            kwargs["out"] = out
        else:
            args[ivy.arg_info(frontend_fn, name="out")["idx"]] = out
        ret = frontend_fn(*args, **kwargs)

        if ivy.native_inplace_support:
            # these backends do not always support native inplace updates
            assert ret.data is out.data

    if "bfloat16" in input_dtypes:
        return  # bfloat16 is not supported by numpy

    # create NumPy args
    args_np = ivy.nested_map(
        args_ivy,
        lambda x: ivy.to_numpy(x._data) if isinstance(x, ivy.Array) else x,
    )
    kwargs_np = ivy.nested_map(
        kwargs_ivy,
        lambda x: ivy.to_numpy(x._data) if isinstance(x, ivy.Array) else x,
    )

    # temporarily set frontend framework as backend
    ivy.set_backend(frontend)
    try:
        # check for unsupported dtypes in frontend framework
        function = getattr(ivy.functional.frontends.__dict__[frontend], fn_name)
        test_unsupported = check_unsupported_dtype(
            fn=function, input_dtypes=input_dtypes, all_as_kwargs_np=all_as_kwargs_np
        )

        # create frontend framework args
        args_frontend = ivy.nested_map(
            args_np,
            lambda x: ivy.native_array(x) if isinstance(x, np.ndarray) else x,
        )
        kwargs_frontend = ivy.nested_map(
            kwargs_np,
            lambda x: ivy.native_array(x) if isinstance(x, np.ndarray) else x,
        )

        # fix for torch not accepting string args for dtype
        if "dtype" in kwargs_frontend and frontend == "torch":
            kwargs_frontend["dtype"] = ivy.as_native_dtype(kwargs_frontend["dtype"])

        # compute the return via the frontend framework
        frontend_fw = importlib.import_module(".".join([frontend] + frontend_submods))
        if test_unsupported:
            test_unsupported_function(
                fn=frontend_fw.__dict__[fn_name],
                args=args_frontend,
                kwargs=kwargs_frontend,
            )
            return
        frontend_ret = frontend_fw.__dict__[fn_name](*args_frontend, **kwargs_frontend)

        # tuplify the frontend return
        if not isinstance(frontend_ret, tuple):
            frontend_ret = (frontend_ret,)

        # flatten the frontend return and convert to NumPy arrays
        frontend_ret_idxs = ivy.nested_indices_where(frontend_ret, ivy.is_native_array)
        frontend_ret_flat = ivy.multi_index_nest(frontend_ret, frontend_ret_idxs)
        frontend_ret_np_flat = [ivy.to_numpy(x) for x in frontend_ret_flat]
    except Exception as e:
        ivy.unset_backend()
        raise e
    # unset frontend framework from backend
    ivy.unset_backend()

    # assuming value test will be handled manually in the test function
    if not test_values:
        return ret, frontend_ret

    # flatten the return
    ret_np_flat = flatten(ret=ret)

    # value tests, iterating through each array in the flattened returns
    value_test(
        ret_np_flat=ret_np_flat,
        ret_from_np_flat=frontend_ret_np_flat,
        rtol=rtol,
        atol=atol,
    )


# Hypothesis #
# -----------#


@st.composite
def array_dtypes(
    draw,
    *,
    num_arrays=st.shared(st.integers(min_value=1, max_value=4), key="num_arrays"),
    available_dtypes=ivy_np.valid_float_dtypes,
    shared_dtype=False,
):
    if not isinstance(num_arrays, int):
        num_arrays = draw(num_arrays)
    if num_arrays == 1:
        dtypes = draw(list_of_length(x=st.sampled_from(available_dtypes), length=1))
    elif shared_dtype:
        dtypes = draw(list_of_length(x=st.sampled_from(available_dtypes), length=1))
        dtypes = [dtypes[0] for _ in range(num_arrays)]
    else:
        unwanted_types = set(ivy.all_dtypes).difference(set(available_dtypes))
        pairs = ivy.promotion_table.keys()
        available_dtypes = [
            pair for pair in pairs if not any([d in pair for d in unwanted_types])
        ]
        dtypes = list(draw(st.sampled_from(available_dtypes)))
        if num_arrays > 2:
            dtypes += [dtypes[i % 2] for i in range(num_arrays - 2)]
    return dtypes


@st.composite
def array_bools(
    draw,
    *,
    num_arrays=st.shared(st.integers(min_value=1, max_value=4), key="num_arrays"),
):
    size = num_arrays if isinstance(num_arrays, int) else draw(num_arrays)
    return draw(st.lists(st.booleans(), min_size=size, max_size=size))


@st.composite
def lists(draw, *, arg, min_size=None, max_size=None, size_bounds=None):
    ints = st.integers(size_bounds[0], size_bounds[1]) if size_bounds else st.integers()
    if isinstance(min_size, str):
        min_size = draw(st.shared(ints, key=min_size))
    if isinstance(max_size, str):
        max_size = draw(st.shared(ints, key=max_size))
    return draw(st.lists(arg, min_size=min_size, max_size=max_size))


@st.composite
def valid_axes(draw, *, ndim=None, size_bounds=None):
    ints = st.integers(size_bounds[0], size_bounds[1]) if size_bounds else st.integers()
    dims = draw(st.shared(ints, key=ndim))
    any_axis_strategy = (
        st.none() | st.integers(-dims, dims - 1) | nph.valid_tuple_axes(dims)
    )
    return draw(any_axis_strategy)


@st.composite
def integers(draw, *, min_value=None, max_value=None):
    if isinstance(min_value, str):
        min_value = draw(st.shared(st.integers(), key=min_value))
    if isinstance(max_value, str):
        max_value = draw(st.shared(st.integers(), key=max_value))
    return draw(st.integers(min_value=min_value, max_value=max_value))


@st.composite
def dtype_and_values(
    draw,
    *,
    available_dtypes=ivy_np.valid_dtypes,
    num_arrays=1,
    min_value=None,
    max_value=None,
    safety_factor=0.95,
    allow_inf=False,
    exclude_min=False,
    exclude_max=False,
    min_num_dims=0,
    max_num_dims=5,
    min_dim_size=1,
    max_dim_size=10,
    shape=None,
    shared_dtype=False,
    ret_shape=False,
    dtype=None,
):
    if not isinstance(num_arrays, int):
        num_arrays = draw(num_arrays)
    if dtype is None:
        dtype = draw(
            array_dtypes(
                num_arrays=num_arrays,
                available_dtypes=available_dtypes,
                shared_dtype=shared_dtype,
            )
        )
    if shape is not None:
        if not isinstance(shape, (tuple, list)):
            shape = draw(shape)
    else:
        shape = draw(
            st.shared(
                get_shape(
                    min_num_dims=min_num_dims,
                    max_num_dims=max_num_dims,
                    min_dim_size=min_dim_size,
                    max_dim_size=max_dim_size,
                ),
                key="shape",
            )
        )
    values = []
    for i in range(num_arrays):
        values.append(
            draw(
                array_values(
                    dtype=dtype[i],
                    shape=shape,
                    min_value=min_value,
                    max_value=max_value,
                    allow_inf=allow_inf,
                    exclude_min=exclude_min,
                    exclude_max=exclude_max,
                    safety_factor=safety_factor,
                )
            )
        )
    if num_arrays == 1:
        dtype = dtype[0]
        values = values[0]
    if ret_shape:
        return dtype, values, shape
    return dtype, values


@st.composite
def dtype_values_axis(
    draw,
    *,
    available_dtypes,
    min_value=None,
    max_value=None,
    allow_inf=True,
    exclude_min=False,
    exclude_max=False,
    min_num_dims=0,
    max_num_dims=5,
    min_dim_size=1,
    max_dim_size=10,
    shape=None,
    shared_dtype=False,
    min_axis=None,
    max_axis=None,
    ret_shape=False,
):
    results = draw(
        dtype_and_values(
            available_dtypes=available_dtypes,
            min_value=min_value,
            max_value=max_value,
            allow_inf=allow_inf,
            exclude_min=exclude_min,
            exclude_max=exclude_max,
            min_num_dims=min_num_dims,
            max_num_dims=max_num_dims,
            min_dim_size=min_dim_size,
            max_dim_size=max_dim_size,
            shape=shape,
            shared_dtype=shared_dtype,
            ret_shape=ret_shape,
        )
    )
    if ret_shape:
        dtype, values, shape = results
    else:
        dtype, values = results
    if not isinstance(values, list):
        return dtype, values, None
    if shape is not None:
        return dtype, values, draw(get_axis(shape=shape))
    axis = draw(integers(min_value=min_axis, max_value=max_axis))
    return dtype, values, axis


# taken from
# https://github.com/data-apis/array-api-tests/array_api_tests/test_manipulation_functions.py
@st.composite
def reshape_shapes(draw, *, shape):
    size = 1 if len(shape) == 0 else math.prod(shape)
    rshape = draw(st.lists(st.integers(0)).filter(lambda s: math.prod(s) == size))
    # assume(all(side <= MAX_SIDE for side in rshape))
    if len(rshape) != 0 and size > 0 and draw(st.booleans()):
        index = draw(st.integers(0, len(rshape) - 1))
        rshape[index] = -1
    return tuple(rshape)


# taken from https://github.com/HypothesisWorks/hypothesis/issues/1115
@st.composite
def subsets(draw, *, elements):
    return tuple(e for e in elements if draw(st.booleans()))


@st.composite
def array_and_indices(
    draw,
    last_dim_same_size=True,
    allow_inf=False,
    min_num_dims=1,
    max_num_dims=5,
    min_dim_size=1,
    max_dim_size=10,
):
    """Generates two arrays x & indices, the values in the indices array are indices
    of the array x. Draws an integers randomly from the minimum and maximum number of
    positional arguments a given function can take.

    Parameters
    ----------
    last_dim_same_size
        True:
            The shape of the indices array is the exact same as the shape of the values
            array.
        False:
            The last dimension of the second array is generated from a range of
            (0 -> dimension size of first array). This results in output shapes such as
            x = (5,5,5,5,5) & indices = (5,5,5,5,3) or x = (7,7) & indices = (7,2)
    allow_inf
        True: inf values are allowed to be generated in the values array
    min_num_dims
        The minimum number of dimensions the arrays can have.
    max_num_dims
        The maximum number of dimensions the arrays can have.
    min_dim_size
        The minimum size of the dimensions of the arrays.
    max_dim_size
        The maximum size of the dimensions of the arrays.

    Returns
    -------
    A strategy that can be used in the @given hypothesis decorator
    which generates arrays of values and indices.

    Examples
    --------
    @given(
        array_and_indices=array_and_indices(
            last_dim_same_size= False
            min_num_dims=1,
            max_num_dims=5,
            min_dim_size=1,
            max_dim_size=10
            )
    )
    @given(
        array_and_indices=array_and_indices( last_dim_same_size= True)
    )
    """
    x_num_dims = draw(st.integers(min_value=min_num_dims, max_value=max_num_dims))
    x_dim_size = draw(st.integers(min_value=min_dim_size, max_value=max_dim_size))
    x = draw(
        dtype_and_values(
            available_dtypes=ivy_np.valid_numeric_dtypes,
            allow_inf=allow_inf,
            ret_shape=True,
            min_num_dims=x_num_dims,
            max_num_dims=x_num_dims,
            min_dim_size=x_dim_size,
            max_dim_size=x_dim_size,
        )
    )
    indices_shape = list(x[2])
    if not (last_dim_same_size):
        indices_dim_size = draw(st.integers(min_value=1, max_value=x_dim_size))
        indices_shape[-1] = indices_dim_size
    indices = draw(
        dtype_and_values(
            available_dtypes=["int32", "int64"],
            allow_inf=False,
            min_value=0,
            max_value=max(x[2][-1] - 1, 0),
            shape=indices_shape,
        )
    )
    x = x[0:2]
    return (x, indices)


@st.composite
def array_values(
    draw,
    *,
    dtype,
    shape,
    min_value=None,
    max_value=None,
    allow_nan=False,
    allow_subnormal=False,
    allow_inf=False,
    exclude_min=True,
    exclude_max=True,
    allow_negative=True,
    safety_factor=0.95,
):
    exclude_min = exclude_min if ivy.exists(min_value) else False
    exclude_max = exclude_max if ivy.exists(max_value) else False
    size = 1
    if isinstance(shape, int):
        size = shape
    else:
        for dim in shape:
            size *= dim
    values = None
    if "int" in dtype:
        if dtype == "int8":
            min_value = ivy.default(min_value, round(-128 * safety_factor))
            max_value = ivy.default(max_value, round(127 * safety_factor))
        elif dtype == "int16":
            min_value = ivy.default(min_value, round(-32768 * safety_factor))
            max_value = ivy.default(max_value, round(32767 * safety_factor))
        elif dtype == "int32":
            min_value = ivy.default(min_value, round(-2147483648 * safety_factor))
            max_value = ivy.default(max_value, round(2147483647 * safety_factor))
        elif dtype == "int64":
            min_value = ivy.default(
                min_value, round(-9223372036854775808 * safety_factor)
            )
            max_value = ivy.default(
                max_value, round(9223372036854775807 * safety_factor)
            )
        elif dtype == "uint8":
            min_value = ivy.default(min_value, round(0 * safety_factor))
            max_value = ivy.default(max_value, round(255 * safety_factor))
        elif dtype == "uint16":
            min_value = ivy.default(min_value, round(0 * safety_factor))
            max_value = ivy.default(max_value, round(65535 * safety_factor))
        elif dtype == "uint32":
            min_value = ivy.default(min_value, round(0 * safety_factor))
            max_value = ivy.default(max_value, round(4294967295 * safety_factor))
        elif dtype == "uint64":
            min_value = ivy.default(min_value, round(0 * safety_factor))
            max_value = ivy.default(
                max_value, round(18446744073709551615 * safety_factor)
            )
        values = draw(list_of_length(x=st.integers(min_value, max_value), length=size))
    elif dtype == "float16":
        values = draw(
            list_of_length(
                x=st.floats(
                    min_value=min_value,
                    max_value=max_value,
                    allow_nan=allow_nan,
                    allow_subnormal=allow_subnormal,
                    allow_infinity=allow_inf,
                    width=16,
                    exclude_min=exclude_min,
                    exclude_max=exclude_max,
                ),
                length=size,
            )
        )
    elif dtype in ["float32", "bfloat16"]:
        values = draw(
            list_of_length(
                x=st.floats(
                    min_value=min_value,
                    max_value=max_value,
                    allow_nan=allow_nan,
                    allow_subnormal=allow_subnormal,
                    allow_infinity=allow_inf,
                    width=32,
                    exclude_min=exclude_min,
                    exclude_max=exclude_max,
                ),
                length=size,
            )
        )
        values = [v * safety_factor for v in values]
    elif dtype == "float64":
        values = draw(
            list_of_length(
                x=st.floats(
                    min_value=min_value,
                    max_value=max_value,
                    allow_nan=allow_nan,
                    allow_subnormal=allow_subnormal,
                    allow_infinity=allow_inf,
                    width=64,
                    exclude_min=exclude_min,
                    exclude_max=exclude_max,
                ),
                length=size,
            )
        )
        values = [v * safety_factor for v in values]
    elif dtype == "bool":
        values = draw(list_of_length(x=st.booleans(), length=size))
    array = np.array(values)
    if dtype != "bool" and not allow_negative:
        array = np.abs(array)
    if isinstance(shape, (tuple, list)):
        array = array.reshape(shape)
    return array.tolist()


@st.composite
def get_shape(
    draw,
    *,
    allow_none=False,
    min_num_dims=0,
    max_num_dims=5,
    min_dim_size=1,
    max_dim_size=10,
):
    if allow_none:
        shape = draw(
            st.none()
            | st.lists(
                st.integers(min_value=min_dim_size, max_value=max_dim_size),
                min_size=min_num_dims,
                max_size=max_num_dims,
            )
        )
    else:
        shape = draw(
            st.lists(
                st.integers(min_value=min_dim_size, max_value=max_dim_size),
                min_size=min_num_dims,
                max_size=max_num_dims,
            )
        )
    if shape is None:
        return shape
    return tuple(shape)


def none_or_list_of_floats(
    *,
    dtype,
    size,
    min_value=None,
    max_value=None,
    exclude_min=False,
    exclude_max=False,
    no_none=False,
):
    """Draws a List containing Nones or Floats.

    Parameters
    ----------
    dtype
        float data type ('float16', 'float32', or 'float64').
    size
        size of the list required.
    min_value
        lower bound for values in the list
    max_value
        upper bound for values in the list
    exclude_min
        if True, exclude the min_value
    exclude_max
        if True, exclude the max_value
    no_none
        if True, List does not contains None

    Returns
    -------
    A strategy that draws a List containing Nones or Floats.
    """
    if no_none:
        if dtype == "float16":
            values = list_of_length(
                x=st.floats(
                    min_value=min_value,
                    max_value=max_value,
                    width=16,
                    allow_subnormal=False,
                    allow_infinity=False,
                    allow_nan=False,
                    exclude_min=exclude_min,
                    exclude_max=exclude_max,
                ),
                length=size,
            )
        elif dtype == "float32":
            values = list_of_length(
                x=st.floats(
                    min_value=min_value,
                    max_value=max_value,
                    width=32,
                    allow_subnormal=False,
                    allow_infinity=False,
                    allow_nan=False,
                    exclude_min=exclude_min,
                    exclude_max=exclude_max,
                ),
                length=size,
            )
        elif dtype == "float64":
            values = list_of_length(
                x=st.floats(
                    min_value=min_value,
                    max_value=max_value,
                    width=64,
                    allow_subnormal=False,
                    allow_infinity=False,
                    allow_nan=False,
                    exclude_min=exclude_min,
                    exclude_max=exclude_max,
                ),
                length=size,
            )
    else:
        if dtype == "float16":
            values = list_of_length(
                x=st.none()
                | st.floats(
                    min_value=min_value,
                    max_value=max_value,
                    width=16,
                    allow_subnormal=False,
                    allow_infinity=False,
                    allow_nan=False,
                    exclude_min=exclude_min,
                    exclude_max=exclude_max,
                ),
                length=size,
            )
        elif dtype == "float32":
            values = list_of_length(
                x=st.none()
                | st.floats(
                    min_value=min_value,
                    max_value=max_value,
                    width=32,
                    allow_subnormal=False,
                    allow_infinity=False,
                    allow_nan=False,
                    exclude_min=exclude_min,
                    exclude_max=exclude_max,
                ),
                length=size,
            )
        elif dtype == "float64":
            values = list_of_length(
                x=st.none()
                | st.floats(
                    min_value=min_value,
                    max_value=max_value,
                    width=64,
                    allow_subnormal=False,
                    allow_infinity=False,
                    allow_nan=False,
                    exclude_min=exclude_min,
                    exclude_max=exclude_max,
                ),
                length=size,
            )
    return values


@st.composite
def get_mean_std(draw, *, dtype):
    """Draws two integers representing the mean and standard deviation for a given data
    type.

    Parameters
    ----------
    draw
        special function that draws data randomly (but is reproducible) from a given
        data-set (ex. list).
    dtype
        data type.

    Returns
    -------
    A strategy that can be used in the @given hypothesis decorator.
    """
    values = draw(none_or_list_of_floats(dtype=dtype, size=2))
    values[1] = abs(values[1]) if values[1] else None
    return values[0], values[1]


@st.composite
def get_bounds(draw, *, dtype):
    """Draws two integers low, high for a given data type such that low < high.

    Parameters
    ----------
    draw
        special function that draws data randomly (but is reproducible) from a given
        data-set (ex. list).
    dtype
        data type.

    Returns
    -------
    A strategy that can be used in the @given hypothesis decorator.
    """
    if "int" in dtype:
        values = draw(array_values(dtype=dtype, shape=2))
        values[0], values[1] = abs(values[0]), abs(values[1])
        low, high = min(values), max(values)
        if low == high:
            return draw(get_bounds(dtype=dtype))
    else:
        values = draw(none_or_list_of_floats(dtype=dtype, size=2))
        if values[0] is not None and values[1] is not None:
            low, high = min(values), max(values)
        else:
            low, high = values[0], values[1]
        if ivy.default(low, 0.0) >= ivy.default(high, 1.0):
            return draw(get_bounds(dtype=dtype))
    return low, high


@st.composite
def get_axis(draw, *, shape, allow_none=False):
    """Draws one or more axis for the given shape.

    Parameters
    ----------
    draw
        special function that draws data randomly (but is reproducible) from a given
        data-set (ex. list).
    shape
        shape of the array.
    allow_none
        if True, allow None to be drawn

    Returns
    -------
    A strategy that can be used in the @given hypothesis decorator.
    """
    axes = len(shape)
    if allow_none:
        axis = draw(
            st.none()
            | st.integers(-axes, axes - 1)
            | st.lists(
                st.integers(-axes, axes - 1),
                min_size=1,
                max_size=axes,
                unique_by=lambda x: shape[x],
            )
        )
    else:
        axis = draw(
            st.integers(-axes, axes - 1)
            | st.lists(
                st.integers(-axes, axes - 1),
                min_size=1,
                max_size=axes,
                unique_by=lambda x: shape[x],
            )
        )
    if type(axis) == list:

        def sort_key(ele, max_len):
            if ele < 0:
                return ele + max_len - 1
            return ele

        axis.sort(key=(lambda ele: sort_key(ele, axes)))
        axis = tuple(axis)
    return axis


@st.composite
def num_positional_args(draw, *, fn_name: str = None):
    """Draws an integers randomly from the minimum and maximum number of positional
    arguments a given function can take.

    Parameters
    ----------
    draw
        special function that draws data randomly (but is reproducible) from a given
        data-set (ex. list).
    fn_name
        name of the function.

    Returns
    -------
    A strategy that can be used in the @given hypothesis decorator.

    Examples
    --------
    @given(
        num_positional_args=num_positional_args(fn_name="floor_divide")
    )
    @given(
        num_positional_args=num_positional_args(fn_name="add")
    )
    """
    num_positional_only = 0
    num_keyword_only = 0
    total = 0
    fn = None
    for i, fn_name_key in enumerate(fn_name.split(".")):
        if i == 0:
            fn = ivy.__dict__[fn_name_key]
        else:
            fn = fn.__dict__[fn_name_key]
    for param in inspect.signature(fn).parameters.values():
        total += 1
        if param.kind == param.POSITIONAL_ONLY:
            num_positional_only += 1
        elif param.kind == param.KEYWORD_ONLY:
            num_keyword_only += 1
    return draw(
        integers(min_value=num_positional_only, max_value=(total - num_keyword_only))
    )


@st.composite
def bool_val_flags(draw, cl_arg: Union[bool, None]):
    if cl_arg is not None:
        return draw(st.booleans().filter(lambda x: x == cl_arg))
    return draw(st.booleans())


def handle_cmd_line_args(test_fn):
    # first four arguments are all fixtures
    def new_fn(data, get_command_line_flags, fw, device, call, *args, **kwargs):
        # inspecting for keyword arguments in test function
        for param in inspect.signature(test_fn).parameters.values():
            if param.name in cmd_line_args:
                kwargs[param.name] = data.draw(
                    bool_val_flags(get_command_line_flags[param.name])
                )
            elif param.name == "data":
                kwargs["data"] = data
            elif param.name == "fw":
                kwargs["fw"] = fw
            elif param.name == "device":
                kwargs["device"] = device
            elif param.name == "call":
                kwargs["call"] = call
        return test_fn(*args, **kwargs)

    return new_fn
