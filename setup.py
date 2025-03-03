from setuptools import setup, find_packages
  
setup(
    name='Rbbm',
    version='0.0.2',
    url='https://github.com/J-Miao/labelling_explanation',
    author='Author Name',
    author_email='author@gmail.com',
    description='Description of my package',
    packages=find_packages(),
    install_requires=["colorful",
                    "gensim",
                    "ipython",
                    "lark",
                    "lime",
                    "matplotlib",
                    "names",
                    "networkx",
                    "nltk",
                    "numpy",
                    "pandas",
                    "psycopg2_binary",
                    "pyitlib",
                    "pytest",
                    "python_Levenshtein",
                    "requests",
                    # "scipy",
                    "setuptools",
                    "SQLAlchemy",
                    # "tensorflow",
                    "textblob",
                    "torch",
                    "tqdm",
                    "transformers"],
    entry_points={
        'console_scripts': [
            'rbbm=rbbm_src.main:main',
        ]},
    )