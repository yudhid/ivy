# global
import ivy


def add(
    x1,
    x2,
    /,
    out=None,
    *,
    where=True,
    casting="same_kind",
    order="k",
    dtype=None,
    subok=True,
):
    if dtype:
        x1 = ivy.astype(ivy.array(x1), ivy.as_ivy_dtype(dtype))
        x2 = ivy.astype(ivy.array(x2), ivy.as_ivy_dtype(dtype))
    ret = ivy.add(x1, x2, out=out)
    if ivy.is_array(where):
        ret = ivy.where(where, ret, ivy.default(out, ivy.zeros_like(ret)), out=out)
    return ret


add.unsupported_dtypes = {"torch": ("float16",)}
