from setuptools import find_packages, setup

setup(
    name="msd",
    version="0.1.0",
    description="DSM-MSD: Model Setup Data Generation (library)",
    python_requires=">=3.8",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=[
        "PyMySQL==1.0.3",
        "cryptography==46.0.0",
        "pandas==2.0.1",
    ],
    package_data={"msd": ["config.ini"]},
    include_package_data=True,
)
