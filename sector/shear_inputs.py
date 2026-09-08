"""Persisted shear geometry choices shared by inputs and calculation."""

SHEAR_SECTION_AUTO = "Automatic - solid rectangle only"
SHEAR_SECTION_CONSTANT = "Constant-width web"
SHEAR_SECTION_VARIABLE = "Variable-width web"
SHEAR_SECTION_CIRCULAR = "Circular section"
SHEAR_SECTION_FORMS = (
    SHEAR_SECTION_AUTO,
    SHEAR_SECTION_CONSTANT,
    SHEAR_SECTION_VARIABLE,
    SHEAR_SECTION_CIRCULAR,
)

SHEAR_DUCT_NONE = "No web ducts"
SHEAR_DUCT_GROUTED_STEEL = "Grouted steel ducts"
SHEAR_DUCT_GROUTED_PLASTIC_THIN = (
    "Grouted plastic ducts - confirmed thin wall"
)
SHEAR_DUCT_GROUTED_PLASTIC_THICK = "Grouted plastic ducts - thick wall"
SHEAR_DUCT_UNGROUTED_OR_SOFT = (
    "Not grouted, soft-filled, or unbonded"
)
SHEAR_DUCT_DETAILS_INCOMPLETE = "Duct details not established"
SHEAR_DUCT_CASES = (
    SHEAR_DUCT_NONE,
    SHEAR_DUCT_GROUTED_STEEL,
    SHEAR_DUCT_GROUTED_PLASTIC_THIN,
    SHEAR_DUCT_GROUTED_PLASTIC_THICK,
    SHEAR_DUCT_UNGROUTED_OR_SOFT,
    SHEAR_DUCT_DETAILS_INCOMPLETE,
)

