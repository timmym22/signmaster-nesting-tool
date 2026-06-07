from setuptools import setup
from Cython.Build import cythonize
setup(
    name="orbital_cy",
    ext_modules=cythonize("core/orbital_cy.pyx", language_level=3),
    script_args=["build_ext", "--inplace"],
)
