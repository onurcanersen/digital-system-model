from setuptools import find_packages, setup

setup(
    name="vae",
    version="0.1.0",
    description="DSM-VAE: Design Verification, Analysis and Evaluation",
    python_requires=">=3.8",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=[
        "Flask==2.3.2",
        "Werkzeug==2.3.4",
        "celery==5.2.3",
        "redis==4.1.1",
        "msd",
    ],
    entry_points={
        "console_scripts": [
            "vae-api=vae.api:main",
            "vae-worker=vae.worker:main",
        ],
    },
    package_data={"vae": ["config.ini", "templates/*.html"]},
    include_package_data=True,
)
