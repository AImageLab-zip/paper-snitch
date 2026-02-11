import json

# Configuration: File paths
INPUT_FILE = "/home/dsantoli/papersnitch/app/annotator/fixtures/categories_embeddings_1536_colored.json"  # The file you want to read
OUTPUT_FILE = "/home/dsantoli/papersnitch/app/annotator/fixtures/categories_embeddings_1536_colored.json"  # The file to save (safer not to overwrite immediately)

# The ordered list of colors (32 items)
NEW_COLORS = [
    # --- 1. COLD (1 Main + 3 Subs) ---
    "#0055FF",  # Royal Blue (Main)
    "#008000",  # Green (Main)
    "#800080",  # Purple (Main)
    "#FF4500",
    "#000080",  # Navy Blue (Scuro)
    "#1E90FF",  # Dodger Blue (Medio)
    "#00FFFF",  # Cyan / Aqua (Acceso - RICHIESTO)
    # --- 2. NATURE (1 Main + 6 Subs) ---
    # Mix di scuri, medi e brillanti per massima distinzione
    "#006400",  # Dark Green (Molto Scuro)
    "#32CD32",  # Lime Green (Medio/Acceso)
    "#7FFF00",  # Chartreuse (Giallo-Verde brillante, ottimo stacco)
    "#00FA9A",  # Medium Spring Green (Verde Menta saturo)
    "#008080",  # Teal (Blu-Verde scuro)
    "#808000",  # Olive (Verde-Marrone)
    # --- 3. CREATIVE (1 Main + 6 Subs) ---
    # Alternanza scuro/medio/acceso
    "#4B0082",  # Indigo (Molto scuro)
    "#8A2BE2",  # Blue Violet (Elettrico)
    "#BA55D3",  # Medium Orchid (Lilla saturo, ben visibile)
    "#FF00FF",  # Magenta / Fuchsia (Neon)
    "#C71585",  # Medium Violet Red (Scuro rossastro)
    "#FF69B4",  # Hot Pink (Rosa acceso)
    # --- 4. WARM & EARTH (1 Main + 13 Subs) ---
    # Invariati perché andavano bene
    "#800000",
    "#DC143C",
    "#CD5C5C",
    "#B7410E",
    "#FF8C00",
    "#E9967A",
    "#B8860B",
    "#D4AF37",
    "#D2B48C",
    "#3E2723",
    "#A0522D",
    "#BC8F8F",
    "#696969",
]


def update_category_colors():
    print(f"--- Opening {INPUT_FILE} ---")

    try:
        # Open and load the JSON file
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Check if the number of items matches the number of colors
        # This is just a warning, the script will still run
        if len(data) != len(NEW_COLORS):
            print(
                f"WARNING: You have {len(data)} items in JSON but {len(NEW_COLORS)} colors in the list."
            )

        # Iterate through the JSON list
        # We use 'enumerate' to get the index (i) to pick the corresponding color
        count = 0
        for i, item in enumerate(data):

            # Stop if we run out of colors (safety check)
            if i >= len(NEW_COLORS):
                print(f"Skipping item {item.get('pk')}: No more colors available.")
                continue

            # Update the 'color' field inside 'fields'
            # We access NEW_COLORS by the current index 'i'
            old_color = item["fields"].get("color", "None")
            new_color = NEW_COLORS[i]

            item["fields"]["color"] = new_color

            # Optional: Print progress
            print(f"Updated PK {item['pk']}: {old_color} -> {new_color}")
            count += 1

        # Save the modified data to a new file
        print(f"--- Saving to {OUTPUT_FILE} ---")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            # indent=2 makes the JSON human-readable
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"Success! Updated {count} categories.")

    except FileNotFoundError:
        print(f"Error: The file '{INPUT_FILE}' was not found.")
    except json.JSONDecodeError:
        print(f"Error: The file '{INPUT_FILE}' is not a valid JSON.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    update_category_colors()
