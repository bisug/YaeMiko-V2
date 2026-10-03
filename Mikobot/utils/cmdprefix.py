from Mikobot import ALLOW_EXCL

# The Kurigram side prefix list, used by the plugins that register handlers on
# the MTProto client rather than the Bot API dispatcher.
PREFIX_HANDLER = ["!", "/", "$"]

if ALLOW_EXCL:
    CMD_STARTERS = (
        "/",
        "!",
        ".",
        "-",
        "$",
        "*",
        "+",
    )
else:
    CMD_STARTERS = ("/",)
