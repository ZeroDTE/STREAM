import os
import pickle
import re
from pathlib import Path

import gensim.downloader as api
import numpy as np
import pandas as pd
from loguru import logger
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from torch.utils.data import Dataset, random_split

from ..commons.load_steps import load_model_preprocessing_steps
# from ..preprocessor import TextPreprocessor :  moved to preprocessor function
from .data_downloader import DataDownloader, get_data_home



AVAILABLE_DATASETS = {
    "BBC_News": "bbc_news",
    "20NewsGroups": "20newsgroups",
    # Add separate entries for each folder
    "Arabic_News": "Arabiya"

}





class TMDataset(Dataset, DataDownloader):
    """
    Topic Modeling Dataset containing methods to fetch and preprocess text data.

    Parameters
    ----------
    name : str, optional
        Name of the dataset.

    Attributes
    ----------
    available_datasets : list of str
        List of available datasets.
    name : str
        Name of the dataset.
    dataframe : pd.DataFrame
        DataFrame containing the dataset.
    embeddings : np.ndarray
        Embeddings for the dataset.
    bow : np.ndarray
        Bag of Words representation of the dataset.
    tfidf : np.ndarray
        TF-IDF representation of the dataset.
    tokens : list of list of str
        Tokenized documents.
    texts : list of str
        Preprocessed text data.
    labels : list of str
        Labels for the dataset.
    language : str
        Language of the dataset.
    preprocessing_steps : dict
        Preprocessing steps to apply to the dataset.

    Notes
    -----
    Available datasets:

    - 20NewsGroup
    - BBC_News
    - Stocktwits_GME
    - Reddit_GME'
    - Reuters'
    - Spotify
    - Spotify_most_popular
    - Poliblogs
    - Spotify_least_popular

    Examples
    --------
    >>> from stream_topic.utils.dataset import TMDataset
    >>> dataset = TMDataset()
    >>> dataset.fetch_dataset("20NewsGroup")
    >>> dataset.preprocess(remove_stopwords=True, lowercase=True)
    >>> dataset.get_bow()
    >>> dataset.get_tfidf()
    >>> dataset.get_word_embeddings()
    >>> dataset.dataframe.head()

    """

    def __init__(self, name=None, language="en"):
        super().__init__()

        self.name = name
        self.dataframe = None
        self.embeddings = None
        self.bow = None
        self.tfidf = None
        self.tokens = None
        self.texts = None
        self.labels = None
        self.language = language
        self.preprocessing_steps = self.default_preprocessing_steps()

    def _load_arabic_dataset(self, dataset_path):
        """Load Arabic dataset from a specific folder path."""
        try:
            # Get the project root directory (where stream_topic is located)
            project_root = Path(__file__).parent.parent.parent
            
            # Define paths relative to project root
            data_path = project_root / "data" / "arabic_datasets" / "arabic_news" / "Arabiya"
            alt_path = Path(dataset_path)  # Use provided path as alternative
            
            # Try different possible paths
            possible_paths = [
                data_path,
                alt_path,
                Path("data/arabic_datasets/arabic_news/Arabiya"),
                Path(os.getcwd()) / "data" / "arabic_datasets" / "arabic_news" / "Arabiya",
                Path("C:/Users/yahya/my_projects/STREAM/stream_topic/data/arabic_datasets/arabic_news/Arabiya")
            ]
            
            # Find first valid path
            valid_path = None
            for path in possible_paths:
                if path.exists():
                    valid_path = path
                    logger.info(f"Found valid dataset path: {valid_path}")
                    break
                else:
                    logger.debug(f"Tried path (not found): {path}")
            
            if valid_path is None:
                raise FileNotFoundError(
                    f"Arabic dataset not found in any of the following locations:\n"
                    f"{chr(10).join(str(p) for p in possible_paths)}\n"
                    f"Please ensure the dataset is placed in one of these locations."
                )

            # Initialize lists for texts and labels
            texts = []
            labels = []
            
            logger.info(f"Loading data from: {valid_path}")
            
            # Track number of files processed and errors
            files_processed = 0
            errors = 0
            
            # Iterate through topic directories
            for topic_dir in valid_path.iterdir():
                if topic_dir.is_dir():
                    logger.info(f"Processing topic: {topic_dir.name}")
                    
                    # Process all txt files in this topic directory
                    for file_path in topic_dir.glob('*.txt'):
                        try:
                            text = file_path.read_text(encoding='utf-8').strip()
                            if text:  # Only add non-empty texts
                                texts.append(text)
                                labels.append(topic_dir.name)
                                files_processed += 1
                        except Exception as e:
                            logger.error(f"Error reading {file_path}: {e}")
                            errors += 1
            
            if not texts:
                raise ValueError(
                    f"No valid text files found in {valid_path}. "
                    "Please check the dataset structure and file contents."
                )
            
            logger.info(f"Successfully processed {files_processed} files with {errors} errors")
            logger.info(f"Found {len(set(labels))} unique topics")
            
            # Create DataFrame
            import pandas as pd
            self.dataframe = pd.DataFrame({
                'text': texts,
                'labels': labels
            })
            
            # Create cache directory if it doesn't exist
            cache_dir = project_root / "cache" / "preprocessed_datasets"
            cache_dir.mkdir(parents=True, exist_ok=True)
            
            # Save preprocessed version to cache
            cache_path = cache_dir / "arabic_news.parquet"
            self.dataframe.to_parquet(cache_path)
            logger.info(f"Cached preprocessed dataset to {cache_path}")
            
            return self.dataframe

        except Exception as e:
            logger.error(f"Error in _load_arabic_dataset: {e}")
            raise
        
        

    def fetch_dataset(self, name: str, dataset_path=None, source: str = "github"):
        """
        Fetch a dataset by name.

        Parameters
        ----------
        name : str
            Name of the dataset to fetch.
        dataset_path : str, optional
            Path to the dataset directory.
        source : str, optional
            Source of the dataset. Options:
            - 'github': Default, fetch from GitHub
            - 'local': Load from local path
            - 'arabic': Load Arabic dataset from local path
        """
        if self.name is None:
            self.name = name
        else:
            logger.info(
                f"Dataset name already provided while instantiating the class: {self.name}"
            )
            logger.info(
                f"Overwriting the dataset name with the name provided in fetch_dataset: {name}"
            )
            self.name = name

        logger.info(f"Fetching dataset: {name}")

        # Handle Arabic datasets
        if name.startswith('Arabic_'):
            try:
                # Define base paths
                project_root = Path(__file__).parent.parent.parent
                default_data_path = project_root / "data" / "arabic_datasets"
                
                # Set dataset path
                if dataset_path is None:
                    data_home = get_data_home()
                    dataset_path = Path(data_home) / "arabic_datasets"
                else:
                    dataset_path = Path(dataset_path)

                # Get specific folder path based on dataset name
                if name in AVAILABLE_DATASETS:
                    specific_path = dataset_path / AVAILABLE_DATASETS[name]
                else:
                    raise ValueError(f"Unknown Arabic dataset: {name}. Available datasets: {list(AVAILABLE_DATASETS.keys())}")

                # Try to load from cache first
                cache_dir = Path(get_data_home()) / "cache" / "preprocessed_datasets"
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_path = cache_dir / f"{name.lower()}.parquet"

                if cache_path.exists():
                    logger.info(f"Loading cached Arabic dataset from {cache_path}")
                    self.dataframe = pd.read_parquet(cache_path)
                else:
                    logger.info(f"Processing Arabic dataset from {specific_path}")
                    self._load_arabic_dataset(specific_path)

                # Initialize info dictionary for Arabic dataset
                self.info = {
                    "name": name,
                    "language": "ar",
                    "source": "local",
                    "preprocessing_steps": {},
                    "num_documents": len(self.dataframe) if self.dataframe is not None else 0,
                    "num_topics": len(self.dataframe['labels'].unique()) if self.dataframe is not None else 0
                }

                if self.dataframe is None or len(self.dataframe) == 0:
                    raise ValueError("No data loaded from the Arabic dataset")

                logger.info(f"Successfully loaded Arabic dataset '{name}' with {len(self.dataframe)} documents")
                return

            except Exception as e:
                logger.error(f"Error loading Arabic dataset: {e}")
                raise

        # Handle other datasets (original functionality)
        if source == "github" and dataset_path is None:
            self.load_custom_dataset_from_url(name)
            data_home = get_data_home()
            dataset_path = os.path.join(data_home, "preprocessed_datasets", name)
            self.info = self.get_info(dataset_path)
        
        elif source == "local" and dataset_path is not None:
            logger.info("Fetching dataset from local path")
            self.load_custom_dataset_from_folder(dataset_path)
            self.info = self.get_info(dataset_path)
        
        elif dataset_path is None:
            logger.info("Fetching dataset from package path")
            dataset_path = self.get_package_dataset_path(name)
            if os.path.exists(dataset_path):
                self.load_custom_dataset_from_folder(dataset_path)
                logger.info(f"Dataset loaded successfully from {dataset_path}")
            else:
                logger.error(f"Dataset path {dataset_path} does not exist.")
                raise ValueError(f"Dataset path {dataset_path} does not exist.")
            self.info = self.get_info(dataset_path)
        
        else:
            logger.error(
                f"Dataset path {dataset_path} does not exist. Please provide the correct path or use the existing dataset."
            )
            raise ValueError(
                f"Dataset path {dataset_path} does not exist. Please provide the correct path or use the existing dataset."
            )

    # After loading any dataset, validate the dataframe
        if self.dataframe is None or len(self.dataframe) == 0:
            raise ValueError("Dataset loading failed: empty or invalid dataframe")

        if 'text' not in self.dataframe.columns:
            raise ValueError("Dataset loading failed: 'text' column missing from dataframe")

        logger.info(f"Dataset loaded successfully with {len(self.dataframe)} documents")
        
        
    def _load_data_to_dataframe(self):
        """
        Load data into a pandas DataFrame.
        """
        self.dataframe = pd.DataFrame(
            {
                "tokens": self.get_corpus(),
                "labels": self.get_labels(),
            }
        )
        self.dataframe["text"] = [" ".join(words)
                                  for words in self.dataframe["tokens"]]
        self.texts = self.dataframe["text"].tolist()
        self.labels = self.dataframe["labels"].tolist()

    def create_load_save_dataset(
        self,
        data,
        dataset_name,
        save_dir,
        doc_column=None,
        label_column=None,
        **kwargs,
    ):
        """
        Create, load, and save a dataset.

        Parameters
        ----------
        data : pd.DataFrame or list
            The data to create the dataset from.
        dataset_name : str
            Name of the dataset.
        save_dir : str
            Directory to save the dataset.
        doc_column : str, optional
            Column name for documents if data is a DataFrame.
        label_column : str, optional
            Column name for labels if data is a DataFrame.
        **kwargs : dict
            Additional columns and their values to include in the dataset.

        Returns
        -------
        Preprocessing
            The preprocessed dataset.
        """
        if isinstance(data, pd.DataFrame):
            if doc_column is None:
                raise ValueError(
                    "doc_column must be specified for DataFrame input")
            documents = [
                self.clean_text(str(row[doc_column])) for _, row in data.iterrows()
            ]
            labels = (
                data[label_column].tolist() if label_column else [
                    None] * len(documents)
            )
        elif isinstance(data, list):
            documents = [self.clean_text(doc) for doc in data]
            labels = [None] * len(documents)
        else:
            raise TypeError(
                "data must be a pandas DataFrame or a list of documents")

        # Initialize preprocessor with kwargs
        preprocessor = TextPreprocessor(**kwargs)
        preprocessed_documents = preprocessor.preprocess_documents(documents)
        self.texts = preprocessed_documents
        self.labels = labels

        # Add additional columns from kwargs to the DataFrame
        additional_columns = {
            key: value for key, value in kwargs.items() if key != "preprocessor"
        }
        additional_columns.update({"text": self.texts, "labels": self.labels})
        self.dataframe = pd.DataFrame(additional_columns)

        # Save the dataset to Parquet format
        if not os.path.exists(save_dir):
            logger.info(f"Dataset save directory does not exist: {save_dir}")
            logger.info(f"Creating directory: {save_dir}")
            os.makedirs(save_dir)

        local_parquet_path = os.path.join(save_dir, f"{dataset_name}.parquet")
        self.dataframe.to_parquet(local_parquet_path)
        logger.info(f"Dataset saved to {local_parquet_path}")

        # Save dataset information
        dataset_info = {
            "name": dataset_name,
            "language": self.language,
            "preprocessing_steps": {
                k: v
                for k, v in preprocessor.__dict__.items()
                if k not in ["stop_words", "language", "contractions_dict"]
            },
        }
        info_path = os.path.join(save_dir, f"{dataset_name}_info.pkl")
        with open(info_path, "wb") as info_file:
            pickle.dump(dataset_info, info_file)
        logger.info(f"Dataset info saved to {info_path}")
        # return preprocessor

    def preprocess(self, model_type=None, custom_stopwords=None, **preprocessing_steps):
        """
        Preprocess the dataset with minimal output.

        Parameters
        ----------
        model_type : str, optional
            The model type to load the preprocessing steps for.
        custom_stopwords : list of str, optional
            Custom stopwords to remove.
        **preprocessing_steps : dict
            Preprocessing steps to apply

        Returns
        -------
        None
            This method modifies the object's texts and dataframe attributes in place.
        """
        from ..preprocessor import TextPreprocessor, ArabicPreprocessor

        # First ensure we have texts to process
        if self.texts is None and self.dataframe is not None:
            self.texts = self.dataframe['text'].tolist()

        if self.texts is None:
            raise ValueError("No texts available for preprocessing. Make sure to load the dataset first.")

        if model_type:
            preprocessing_steps = load_model_preprocessing_steps(model_type)
        previous_steps = self.preprocessing_steps

        # Filter out steps that have already been applied
        filtered_steps = {
            key: (
                False
                if key in previous_steps and previous_steps[key] == value
                else value
            )
            for key, value in preprocessing_steps.items()
        }

        if custom_stopwords:
            filtered_steps["remove_stopwords"] = True
            filtered_steps["custom_stopwords"] = list(set(custom_stopwords))
        else:
            filtered_steps["custom_stopwords"] = []

        # Only preprocess if there are steps that need to be applied
        if filtered_steps:
            try:
                # Don't pass language if it's already in filtered_steps
                language = filtered_steps.pop('language', self.language)

                # Show initial status and sample
                print(f"Found {len(self.texts)} documents to preprocess")
                print("\nSample of first 3 documents:")
                for text in self.texts[:3]:
                    print(f"Processing text: {text[:50]}...")
                print("...(remaining documents omitted)...")
                print("\nPreprocessing in progress...")

                # Create appropriate preprocessor
                if language == "ar":
                    preprocessor = ArabicPreprocessor(
                        remove_diacritics=filtered_steps.get("remove_diacritics", True),
                        remove_punctuation=filtered_steps.get("remove_punctuation", True),
                        remove_numbers=filtered_steps.get("remove_numbers", True),
                        remove_stopwords=filtered_steps.get("remove_stopwords", True),
                        normalize_arabic=filtered_steps.get("normalize_arabic", True),
                        verbose=False

                    )
                    # Silently process all texts
                    self.texts = [preprocessor.preprocess(text) for text in self.texts]
                else:
                    preprocessor = TextPreprocessor(
                        language=language,
                        **filtered_steps,
                    )
                    self.texts = preprocessor.preprocess_documents(self.texts)

                # Update dataframe
                self.dataframe["text"] = self.texts
                self.dataframe["tokens"] = self.dataframe["text"].apply(lambda x: x.split())

                print("Preprocessing completed successfully!")

                # Update info
                self.info.update(
                    {
                        "preprocessing_steps": {
                            k: v
                            for k, v in preprocessor.__dict__.items()
                            if k != "stopwords"
                        }
                    }
                )
            except Exception as e:
                raise RuntimeError(f"Error in dataset preprocessing: {e}") from e
                
        self.update_preprocessing_steps(**filtered_steps)

    def update_preprocessing_steps(self, **preprocessing_steps):
        """
        Update preprocessing steps to True if they were previously False.

        Parameters
        ----------
        preprocessing_steps : dict
            Key-value pairs of preprocessing steps to update.
        """
        for step, value in preprocessing_steps.items():
            if (
                value is True
                and step in self.preprocessing_steps
                and not self.preprocessing_steps[step]
            ):
                self.preprocessing_steps[step] = True
            elif value is True and step not in self.preprocessing_steps:
                self.preprocessing_steps[step] = True

    def get_info(self, dataset_path=None):
        """
        Load and return the dataset information.

        Parameters
        ----------
        name : str
            Name of the dataset.
        save_dir : str
            Directory where the dataset is saved.

        Returns
        -------
        dict
            Dictionary containing the dataset information.
        """
        if dataset_path is None:
            dataset_path = self.get_package_dataset_path(self.name)
        elif os.path.exists(dataset_path):
            pass
        else:
            raise ValueError(f"Dataset path {dataset_path} does not exist.")

        info_path = os.path.join(dataset_path, f"{self.name}_info.pkl")
        if os.path.exists(info_path):
            with open(info_path, "rb") as info_file:
                dataset_info = pickle.load(info_file)
            return dataset_info
        else:
            raise FileNotFoundError(
                f"Dataset info file {info_path} does not exist.")

    @staticmethod
    def clean_text(text):
        """
        Clean the input text.

        Parameters
        ----------
        text : str
            Input text to clean.

        Returns
        -------
        str
            Cleaned text.
        """
        text = text.replace("\n", " ").replace("\r", " ").replace("\\", "")
        text = re.sub(r"[{}[\]-]", "", text)
        text = text.encode("utf-8", "replace").decode("utf-8")
        return text

    def __len__(self):
        """
        Get the number of samples in the dataset.

        Returns
        -------
        int
            Number of samples.
        """
        return len(self.texts)

    def __getitem__(self, idx):
        """
        Get a sample by index.

        Parameters
        ----------
        idx : int
            Index of the sample.

        Returns
        -------
        dict
            Sample at the given index.
        """
        item = {"text": self.texts[idx]}
        if self.labels[idx] is not None:
            item["label"] = self.labels[idx]
        if self.embeddings is not None:
            item["embedding"] = self.embeddings[idx]
        if self.bow is not None:
            item["bow"] = self.bow[idx]
        if self.tokens is not None:
            item["tokens"] = self.tokens[idx]
        if self.tfidf is not None:
            item["tfidf"] = self.tfidf[idx]
        return item

    def get_corpus(self):
        """
        Get the corpus (tokens) from the dataframe.

        Returns
        -------
        list of list of str
            Corpus tokens.
        """
        return self.dataframe["tokens"].tolist()

    def get_vocabulary(self):
        """
        Get the vocabulary from the dataframe.

        Returns
        -------
        list of str
            Vocabulary.
        """
        # Flatten the list of lists and convert to set for unique words
        all_tokens = [
            token for sublist in self.dataframe["tokens"].tolist() for token in sublist
        ]
        return list(set(all_tokens))

    def get_labels(self):
        """
        Get the labels from the dataframe.

        Returns
        -------
        list of str
            Labels.
        """
        return self.dataframe["labels"].tolist()

    def split_dataset(self, train_ratio=0.8, val_ratio=0.2, seed=None):
        """
        Split the dataset into train, validation, and test sets.

        Parameters
        ----------
        train_ratio : float, optional
            Ratio of the training set, by default 0.8.
        val_ratio : float, optional
            Ratio of the validation set, by default 0.1.
        test_ratio : float, optional
            Ratio of the test set, by default 0.1.
        seed : int, optional
            Random seed for shuffling, by default None.

        Returns
        -------
        tuple of Dataset
            Train, validation, and test datasets.
        """
        total_size = len(self)

        if train_ratio < 0 or val_ratio < 0:
            raise ValueError("Train, val and test ratios must be positive")

        if train_ratio + val_ratio != 1.0:
            raise ValueError("Train, validation and test ratios must sum to 1")

        train_size = int(train_ratio * total_size)
        val_size = total_size - train_size

        if seed is not None:
            np.random.seed(seed)

        train_dataset, val_dataset = random_split(self, [train_size, val_size])
        return train_dataset, val_dataset

    def get_bow(self, **kwargs):
        """
        Get the Bag of Words representation of the corpus.

        Parameters
        ----------
        **kwargs : dict, optional
            Additional arguments to pass to CountVectorizer.

        Returns
        -------
        scipy.sparse.csr_matrix
            BOW matrix.
        list of str
            Feature names.
        """
        corpus = [" ".join(tokens) for tokens in self.get_corpus()]
        vectorizer = CountVectorizer(**kwargs)
        self.bow = vectorizer.fit_transform(
            corpus).toarray().astype(np.float32)
        return self.bow, vectorizer.get_feature_names_out()

    def get_tfidf(self, **kwargs):
        """
        Get the TF-IDF representation of the corpus.

        Parameters
        ----------
        **kwargs : dict, optional
            Additional arguments to pass to TfidfVectorizer.

        Returns
        -------
        scipy.sparse.csr_matrix
            TF-IDF matrix.
        list of str
            Feature names.
        """
        corpus = [" ".join(tokens) for tokens in self.get_corpus()]
        vectorizer = TfidfVectorizer(**kwargs)
        self.tfidf = vectorizer.fit_transform(corpus).toarray()
        return self.tfidf, vectorizer.get_feature_names_out()

    def has_word_embeddings(self, model_name):
        """
        Check if word embeddings are available for the dataset.

        Parameters
        ----------
        model_name : str
            Name of the pre-trained model.

        Returns
        -------
        bool
            True if word embeddings are available, False otherwise.
        """
        return self.has_embeddings(model_name, "word_embeddings")

    def get_word_embeddings(self, model_name="glove-wiki-gigaword-100", vocab=None):
        """
        Get the word embeddings for the vocabulary using a pre-trained model.

        Parameters
        ----------
        model_name : str, optional
            Name of the pre-trained model to use, by default 'glove-wiki-gigaword-100'.
        vocab : list of str, optional

        Returns
        -------
        dict
            Dictionary mapping words to their embeddings.
        """

        assert model_name in [
            "glove-wiki-gigaword-100",
            "paraphrase-MiniLM-L3-v2",
        ], f"model name {model_name} not supported. Can be 'glove-wiki-gigaword-100' and 'paraphrase-MiniLM-L3-v2'"

        if vocab is None:
            vocabulary = self.get_vocabulary()
        else:
            vocabulary = vocab

        if self.has_word_embeddings(model_name):
            return self.get_embeddings(model_name, "word_embeddings")

        if model_name == "glove_wiki_gigaword_100":
            # Load pre-trained model
            model = api.load(model_name)

            embeddings = {word: model[word]
                          for word in vocabulary if word in model}

        if model_name == "paraphrase-MiniLM-L3-v2":
            model = SentenceTransformer(model_name)
            vocabulary = list(vocabulary)
            embeddings = model.encode(
                vocabulary, convert_to_tensor=True, show_progress_bar=True
            )

            embeddings = {word: embeddings[i]
                          for i, word in enumerate(vocabulary)}

            assert len(embeddings) == len(
                vocabulary
            ), "Embeddings and vocabulary length mismatch"

        return embeddings
