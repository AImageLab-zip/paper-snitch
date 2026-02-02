def create_categories(apps):
    AnnotationCategory = apps.get_model("annotator", "AnnotationCategory")

    # Data Structure:
    # Key: Parent Name
    # Value: Dict containing 'color' and 'subcategories' (list of tuples: (Short Name, Full Description))

    structure = {
        "Models and Algorithms": {
            "color": "#3498db",  # Blue
            "order": 1,
            "subs": [
                (
                    "Model/Algorithm Description",
                    "A description of the mathematical setting, algorithm, and/or model.",
                ),
                ("Assumptions", "An explanation of any assumptions."),
                (
                    "Software Framework",
                    "A declaration of what software framework and version you used.",
                ),
            ],
        },
        "Datasets": {
            "color": "#2ecc71",  # Green
            "order": 2,
            "subs": [
                (
                    "Statistics",
                    "The relevant statistics, such as the number of examples.",
                ),
                ("Study Cohort", "Description of the study cohort."),
                (
                    "Existing Datasets Info",
                    "For existing datasets, citations as well as descriptions if they are not publicly available.",
                ),
                (
                    "Data Collection Process",
                    "For new data collected, a complete description of the data collection process, such as descriptions of the experimental setup, device(s) used, image acquisition parameters, subjects/objects involved, instructions to annotators, and methods for quality control.",
                ),
                (
                    "Download Link",
                    "A link to a downloadable version of the dataset (if public).",
                ),
                (
                    "Ethics Approval",
                    "Whether ethics approval was necessary for the data.",
                ),
            ],
        },
        "Code Related": {
            "color": "#9b59b6",  # Purple
            "order": 3,
            "subs": [
                ("Dependencies", "Specification of dependencies."),
                ("Training Code", "Training code."),
                ("Evaluation Code", "Evaluation code."),
                ("Pre-trained Models", "(Pre-)trained model(s)."),
                (
                    "Dataset for Code",
                    "Dataset or link to the dataset needed to run the code.",
                ),
                (
                    "README & Results",
                    "README file including a table of results accompanied by precise commands to run to produce those results.",
                ),
            ],
        },
        "Experimental Results": {
            "color": "#e67e22",  # Orange
            "order": 4,
            "subs": [
                (
                    "Hyperparameters",
                    "The range of hyperparameters considered, the method to select the best hyperparameter configuration, and the specification of all hyperparameters used to generate results.",
                ),
                (
                    "Sensitivity Analysis",
                    "Information on sensitivity regarding parameter changes.",
                ),
                (
                    "Training/Eval Runs",
                    "The exact number of training and evaluation runs.",
                ),
                (
                    "Baseline Methods",
                    "Details on how baseline methods were implemented and tuned.",
                ),
                (
                    "Data Splits",
                    "The details of training / validation / testing splits.",
                ),
                (
                    "Evaluation Metrics",
                    "A clear definition of the specific evaluation metrics and/or statistics used to report results.",
                ),
                (
                    "Central Tendency & Variation",
                    "A description of results with central tendency (e.g., mean) & variation (e.g., error bars).",
                ),
                (
                    "Statistical Significance",
                    "An analysis of the statistical significance of reported differences in performance between methods.",
                ),
                (
                    "Runtime / Energy Cost",
                    "The average runtime for each result, or estimated energy cost.",
                ),
                ("Memory Footprint", "A description of the memory footprint."),
                (
                    "Failure Analysis",
                    "An analysis of situations in which the method failed.",
                ),
                (
                    "Computing Infrastructure",
                    "A description of the computing infrastructure used (hardware and software).",
                ),
                ("Clinical Significance", "Discussion of clinical significance."),
            ],
        },
    }

    # Execution Logic
    for parent_name, data in structure.items():
        # Create Parent
        parent_obj, created = AnnotationCategory.objects.get_or_create(
            name=parent_name,
            defaults={
                "color": data["color"],
                "description": f"Main category for {parent_name}",
                "order": data["order"],
            },
        )

        # Create Subcategories
        for index, (sub_name, sub_desc) in enumerate(data["subs"]):
            AnnotationCategory.objects.get_or_create(
                name=sub_name,
                parent=parent_obj,
                defaults={
                    "color": data["color"],  # Inherit parent color
                    "description": sub_desc,
                    "order": index + 1,
                },
            )


def remove_categories(apps, schema_editor):
    AnnotationCategory = apps.get_model("annotator", "AnnotationCategory")
    # Be careful: this deletes ALL categories with these names.
    # Usually safer to do nothing or only delete if you are sure.
    parents = [
        "Models and Algorithms",
        "Datasets",
        "Code Related",
        "Experimental Results",
    ]
    AnnotationCategory.objects.filter(name__in=parents).delete()
