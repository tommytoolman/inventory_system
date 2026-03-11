import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Polygon, PathPatch
from matplotlib.path import Path
from matplotlib import font_manager
import matplotlib.transforms as transforms
import os

# 1. Setup the figure with True Transparency
fig, ax = plt.subplots(figsize=(10, 10))
fig.patch.set_alpha(0.0) # Transparent background
ax.axis('off')
ax.set_aspect('equal')
ax.set_xlim(-1.2, 1.2)
ax.set_ylim(-1.2, 1.2)

# Color definition
color = (46/255, 49/255, 50/255) # rgb(46 49 50)

# 2. Create the Single Circle of Stars
def draw_star(center_x, center_y, size, angle_deg):
    # Create a star polygon
    angles = np.linspace(np.pi/2, 2.5*np.pi, 11) # 5 points
    # Radii for outer and inner points
    r_outer = size
    r_inner = size * 0.382

    vertices = []
    for i, ang in enumerate(angles[:-1]):
        r = r_outer if i % 2 == 0 else r_inner
        # Rotate the star itself to align with the circle
        rot_ang = np.radians(angle_deg - 90) # Adjust orientation

        # Vertex relative to star center (unrotated)
        vx = r * np.cos(ang)
        vy = r * np.sin(ang)

        # Rotate vertex
        vx_rot = vx * np.cos(rot_ang) - vy * np.sin(rot_ang)
        vy_rot = vx * np.sin(rot_ang) + vy * np.cos(rot_ang)

        vertices.append([center_x + vx_rot, center_y + vy_rot])

    star = Polygon(vertices, closed=True, color=color, zorder=10)
    ax.add_patch(star)

# Draw the ring
radius = 1.0
num_stars = 40
for i in range(num_stars):
    angle_deg = (360 / num_stars) * i
    angle_rad = np.radians(angle_deg)
    x = radius * np.cos(angle_rad)
    y = radius * np.sin(angle_rad)
    draw_star(x, y, 0.08, angle_deg) # 0.08 is star size

# 3. Add the "Artist Owned" Text
# Using a bold sans-serif font available in the environment
font_props = font_manager.FontProperties(family='DejaVu Sans', weight='heavy', style='italic', size=65)

# Place text at 20 degree angle (visual slant)
# "Artist"
ax.text(0, 0.15, "Artist",
        ha='center', va='bottom',
        rotation=20,
        color=color,
        fontproperties=font_props)

# "Owned"
ax.text(0.05, -0.05, "Owned",
        ha='center', va='top',
        rotation=20,
        color=color,
        fontproperties=font_props)


# 4. Draw a Better Electric Guitar (Strat style)
# Defining a path for a more detailed silhouette
verts = [
    (0.0, -0.65), # Bottom strap button
    (-0.15, -0.63), # Bottom curve left
    (-0.25, -0.5), # Lower bout left
    (-0.22, -0.35), # Waist left
    (-0.28, -0.2), # Upper horn bottom
    (-0.25, -0.05), # Upper horn tip
    (-0.15, -0.15), # Upper horn top / neck join
    (-0.06, -0.12), # Neck left side base
    (-0.05, 0.25),  # Neck left side top
    (-0.10, 0.28),  # Headstock curve
    (-0.08, 0.38),  # Headstock tip
    (0.05, 0.35),   # Headstock right
    (0.04, 0.25),   # Neck right top
    (0.05, -0.12),  # Neck right base / lower horn top
    (0.15, -0.2),   # Lower horn tip
    (0.12, -0.35),  # Waist right
    (0.25, -0.5),   # Lower bout right
    (0.15, -0.63),  # Bottom curve right
    (0.0, -0.65),   # Close
]

codes = [Path.MOVETO] + [Path.LINETO] * (len(verts) - 2) + [Path.CLOSEPOLY]
path = Path(verts, codes)
patch = PathPatch(path, facecolor=color, lw=0, zorder=5)

# Transform the guitar: move it down and rotate it to match text
trans = transforms.Affine2D().rotate_deg(20).translate(0.1, -0.5) + ax.transData
patch.set_transform(trans)

ax.add_patch(patch)

# Save to ebay static dir
output_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'static', 'ebay', 'artist_owned_badge.png')
output_path = os.path.abspath(output_path)
plt.savefig(output_path, format='png', transparent=True, dpi=300, bbox_inches='tight', pad_inches=0.1)
print(f"Saved to: {output_path}")
