from setuptools import setup

LONG_DESCRIPTION = ""
try:
    with open("README.md", "r", encoding="utf-8") as f:
        LONG_DESCRIPTION = f.read()
except OSError:
    LONG_DESCRIPTION = "FastFold PyMOL Agent"

setup(
    name="fastfold-pymol-agent",
    version="0.1.0",
    description="FastFold-branded natural-language agent for PyMOL",
    long_description=LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    author="FastFold AI",
    url="https://github.com/fastfold-ai/fastfold-pymol-agent",
    # Flat-layout project: map the import package "fastfold_pymol_agent" to repo root.
    packages=["fastfold_pymol_agent"],
    package_dir={"fastfold_pymol_agent": "."},
    python_requires=">=3.8",
    install_requires=[
        "anthropic>=0.20.0",
        "claude-agent-sdk>=0.1.72",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Force Compatible",
        "Topic :: Scientific/Engineering :: Bio-Informatics",
        "Topic :: Scientific/Engineering :: Visualization",
    ],
)
