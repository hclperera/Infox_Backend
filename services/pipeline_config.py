"""Resolve grouping classes from the detector's actual class metadata."""
from services.grouping import GridConfig


def grid_config_for_vision(vision, settings=None):
    settings = dict(settings or {})
    settings.setdefault('front_class_id', vision.get('front_class_id', 2))
    if settings.get('recover_back_dots'):
        names = vision.get('class_names')
        if names is not None:
            items = names.items() if isinstance(names, dict) else enumerate(names)
            names = {int(key): str(value).strip().lower() for key, value in items}
            if 'back_class_id' not in settings:
                matches = [key for key, name in names.items()
                           if name in ('back', 'verso', 'back dots', 'back_dot')]
                if len(matches) != 1:
                    raise ValueError('Cannot resolve back class; configure back_class_id explicitly')
                settings['back_class_id'] = matches[0]
            if settings['back_class_id'] not in names:
                raise ValueError('Configured back_class_id is absent from detector classes')
        # Bare YOLO files have no metadata. Preserve their existing default.
        if settings.get('back_class_id', 1) == settings['front_class_id']:
            raise ValueError('Front and back class IDs must differ for classification recovery')
    return GridConfig(**settings)
