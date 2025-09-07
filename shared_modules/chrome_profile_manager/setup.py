from setuptools import setup, find_packages

setup(
    name="chrome-profile-manager",
    version="1.0.0",
    author="TwitterBot Project",
    description="プロファイル作成とChrome起動を統合管理する汎用ライブラリ",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    packages=find_packages(),
    install_requires=[
        "selenium>=4.0.0",
        "webdriver-manager>=3.8.0",
    ],
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    keywords="selenium chrome profile webdriver automation",
    project_urls={
        "Source": "https://github.com/your-username/chrome-profile-manager",
        "Bug Reports": "https://github.com/your-username/chrome-profile-manager/issues",
    },
)