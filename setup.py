from setuptools import find_packages, setup

setup(
    name="myagent",
    version="1.0.0",
    description="Terminal AI agent: Claude plans, Gemini executes",
    python_requires=">=3.10",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "": ["prompts/*.txt"],
    },
    install_requires=[
        "anthropic>=0.25.0",
        "google-generativeai>=0.5.0",
        "rich>=13.0.0",
    ],
    entry_points={
        "console_scripts": [
            "myagent=myagent.cli:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
