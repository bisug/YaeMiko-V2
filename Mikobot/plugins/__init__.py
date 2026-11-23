from Mikobot import LOAD, NO_LOAD
from Mikobot.logger import LOGGER


def __list_all_modules():
    import sys
    from pathlib import Path

    # This generates a list of modules in this folder for the * in __main__ to work.
    mod_paths = Path(__file__).parent.glob("*.py")
    all_modules = [
        f.stem
        for f in mod_paths
        if f.is_file() and f.suffix == ".py" and not f.name.endswith("__init__.py")
    ]

    if LOAD or NO_LOAD:
        to_load = LOAD
        if to_load:
            if not all(
                any(mod == module_name for module_name in all_modules)
                for mod in to_load
            ):
                LOGGER.error("Invalid load order names. Quitting...")
                sys.exit(1)

            all_modules = sorted(set(all_modules) - set(to_load))
            to_load = list(all_modules) + to_load

        else:
            to_load = all_modules

        if NO_LOAD:
            LOGGER.info("Not loading: %s", NO_LOAD)
            return [item for item in to_load if item not in NO_LOAD]

        return to_load

    return all_modules


ALL_MODULES = __list_all_modules()
LOGGER.info("Modules to load: %s", str(ALL_MODULES))
__all__ = ALL_MODULES + ["ALL_MODULES"]
