# Copyright 2025 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl)
"""Parse Python module files and extract Odoo data models from them."""

import ast

BASE_CLASSES = [
    "BaseModel",
    "AbstractModel",
    "Model",
    "TransientModel",
]

FIELD_TYPES = [
    "Boolean",
    "Char",
    "Integer",
    "Float",
    "Date",
    "Datetime",
    "Selection",
    "Many2one",
    "One2many",
    "Many2many",
]


class PyFile:
    """Python module file.

    Such file cound contain Odoo data models.
    """

    def __init__(self, path: str):
        if not path.endswith(".py"):
            raise ValueError(f"{path} is not a Python file")
        self.path = path
        self.content = self._parse_file()
        self.models = self._get_models()

    def _parse_file(self):
        with open(self.path) as file_:
            content = file_.read()
            return ast.parse(content)

    def _get_models(self):
        models = {}
        for elt in self.content.body:
            if isinstance(elt, ast.ClassDef) and OdooModel.is_model(elt):
                model = OdooModel(elt)
                # Support corner case where the same data model is
                # declared/inherited multiple times in the same file
                # (each of them will add a new data model entry).
                key = f"{self.path}:{elt.name}"
                models[key] = model.to_dict()
            elif isinstance(elt, ast.ClassDef) and OdooModel.is_base_class(
                elt
            ):
                model = OdooModel(elt)
                models[elt.name] = model.to_dict()
        return models

    def to_dict(self):
        return {"models": self.models}


class OdooModel:
    """Odoo data model representation."""

    def __init__(self, ast_cls):
        assert self.is_model(ast_cls) or self.is_base_class(ast_cls)
        self.type_ = self._get_type(ast_cls)
        self.name = self._get_attr_value(ast_cls, "_name")
        self.inherit = self._get_attr_value(ast_cls, "_inherit")
        self.inherits = self._get_attr_value(ast_cls, "_inherits")
        self.auto = self._get_attr_value(
            ast_cls, "_auto"
        )  # None / False / True
        self.order = self._get_attr_value(ast_cls, "_order")
        self.fields = self._get_fields(ast_cls)
        self.methods = self._get_methods(ast_cls)

    @classmethod
    def is_model(cls, ast_cls):
        """Check if `ast_cls` is an Odoo data model."""
        name = cls._get_attr_value(ast_cls, "_name")
        inherit = cls._get_attr_value(ast_cls, "_inherit")
        return bool(name or inherit)

    @classmethod
    def is_base_class(cls, ast_cls):
        """Check if `ast_cls` is an Odoo base class."""
        bases = []
        for base in ast_cls.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(base.attr)
        if ast_cls.name == "BaseModel" and not bases:
            return True
        if ast_cls.name in BASE_CLASSES and set(bases) & set(BASE_CLASSES):
            return True
        return False

    @staticmethod
    def _get_type(ast_cls):
        """Return the type of the Odoo data model.

        Available types are 'Model', 'AbstractModel', 'TransientModel'...
        """
        for base in ast_cls.bases:
            # Support e.g.'models.Model'
            if isinstance(base, ast.Attribute):
                return base.attr
            # Support e.g. 'Model'
            if isinstance(base, ast.Name):
                return base.id

    @staticmethod
    def _get_attr_value(ast_cls: ast.ClassDef, attr_name: str):
        """Return value of an attribute.

        It supports only attributes having basic values. E.g. if an attribute
        takes its value from a function call, nothing will be returned.
        """
        for elt in ast_cls.body:
            if isinstance(elt, ast.Assign) and elt.targets:
                for target in elt.targets:
                    if target.id != attr_name:
                        continue
                    # _name, _inherit, _description, _auto, _order...
                    if isinstance(elt.value, ast.Constant):
                        return elt.value.value
                    # _inherit
                    if isinstance(elt.value, ast.Constant):
                        return elt.value.value
                    # _inherits
                    if isinstance(elt.value, ast.Dict):
                        # iterate on dict keys/values
                        values = {}
                        for key, value in zip(
                            elt.value.keys, elt.value.values
                        ):
                            if isinstance(key, ast.Constant) and isinstance(
                                value, ast.Constant
                            ):
                                values[key.value] = value.value
                        if values:
                            return values

    @staticmethod
    def _get_fields(ast_cls: ast.ClassDef):
        """Return the fields declared in current data model."""
        fields = {}
        for elt in ast_cls.body:
            if not OdooField.is_field(elt):
                continue
            field = OdooField(elt)
            fields[field.name] = field.to_dict()
        return fields

    @staticmethod
    def _get_methods(ast_cls: ast.ClassDef):
        """Return the methods declared in current data model."""
        methods = {}
        for elt in ast_cls.body:
            if not OdooMethod.is_method(elt):
                continue
            method = OdooMethod(elt)
            methods[method.name] = method.to_dict()
        return methods

    def to_dict(self):
        data = {"type": self.type_}
        if self.auto is not None:
            data["auto"] = self.auto
        for attr in ("name", "inherit", "inherits", "fields", "methods"):
            if getattr(self, attr):
                data[attr] = getattr(self, attr)
        return data


class OdooField:
    """Odoo field representation."""

    def __init__(self, ast_cls):
        assert self.is_field(ast_cls)
        self.name = ast_cls.targets[0].id
        self.type_ = self._extract_type(ast_cls)

    @classmethod
    def is_field(cls, ast_cls):
        """Check if `ast_cls` is an Odoo field."""
        if isinstance(ast_cls, ast.Assign) and ast_cls.targets:
            if not isinstance(ast_cls.value, ast.Call):
                return False
            field_type = cls._extract_type(ast_cls)
            if not field_type:
                return False
            return True
        return False

    @classmethod
    def _extract_type(cls, ast_cls):
        field_type = None
        # Support e.g.'fields.Char'
        if isinstance(ast_cls.value.func, ast.Attribute):
            field_type = ast_cls.value.func.attr
        # Support e.g. 'Char' (not common)
        elif isinstance(ast_cls.value.func, ast.Name):
            field_type = ast_cls.value.func.id
        if field_type in FIELD_TYPES:
            return field_type

    def to_dict(self):
        return {"name": self.name, "type": self.type_}


class OdooMethod:
    """Odoo data model method representation."""

    def __init__(self, ast_cls):
        assert self.is_method(ast_cls)
        self.name = ast_cls.name
        self.decorators = self._extract_decorators(ast_cls)
        self.signature = self._extract_method_signature(ast_cls)

    @classmethod
    def is_method(cls, ast_cls):
        """Check if `ast_cls` is a method/function."""
        if isinstance(ast_cls, ast.FunctionDef):
            # Skip private methods
            return not ast_cls.name.startswith("__")

    @classmethod
    def _extract_decorators(cls, ast_cls):
        decorators = []
        for dec in ast_cls.decorator_list:
            # E.g. @model
            if isinstance(dec, ast.Name):
                decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                # E.g. @api.model
                decorators.append(f"{dec.value.id}.{dec.attr}")
            elif isinstance(dec, ast.Call):
                # E.g. @api.depends(...)
                if isinstance(dec.func, ast.Name):
                    deco = f"{dec.func.id}"
                elif isinstance(dec.func, ast.Attribute):
                    deco = f"{dec.func.value.id}.{dec.func.attr}"
                args = cls._extract_decorator_signature(dec)
                deco += "({})".format(", ".join(args))
                decorators.append(deco)
        return tuple(decorators)

    @classmethod
    def _extract_decorator_signature(cls, ast_cls):
        assert isinstance(ast_cls, ast.Call)
        args = []
        for arg in ast_cls.args:
            args.append(ast_to_string(arg))
        kwargs = []
        for keyword in ast_cls.keywords:
            kwargs.append(f"{keyword.arg}=" + ast_to_string(keyword.value))
        return tuple(args + kwargs)

    @classmethod
    def _extract_method_signature(cls, ast_cls):
        assert isinstance(ast_cls, ast.FunctionDef)
        args = [arg.arg for arg in ast_cls.args.args]
        defaults = []
        for default in ast_cls.args.defaults:
            defaults.append(ast_to_string(default))
        signature = args[:]
        defaults.reverse()
        for i, default in enumerate(defaults):
            arg = signature[-i - 1]
            signature[-i - 1] = f"{arg}={default}"
        return tuple(signature)

    def to_dict(self):
        data = {"name": self.name, "signature": self.signature}
        if self.decorators:
            data["decorators"] = self.decorators
        return data


def ast_to_string(elt):
    """Return the string representation of an ast element."""
    if isinstance(elt, ast.Name):
        return elt.id
    if isinstance(elt, ast.Call) or isinstance(elt, ast.Lambda):
        return "<Call()>"
    if isinstance(elt, ast.List):
        return "<List()>"
    if isinstance(elt, ast.Tuple):
        return "<Tuple()>"
    # ast.Constant
    return repr(elt.value)
