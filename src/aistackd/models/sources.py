"""Model and backend acquisition policy constants."""

PRIMARY_BACKEND = "llama.cpp"
PRIMARY_MODEL_SOURCE = "llmfit"
FALLBACK_MODEL_SOURCE = "hugging_face"
BACKEND_ACQUISITION_POLICY = "prebuilt_first_source_fallback"
MODEL_SOURCE_POLICY = "llmfit_first_hugging_face_fallback"
