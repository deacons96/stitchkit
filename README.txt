STITCHKIT 1.2 beta
Digitize artwork, make faux-merrow patches and appliqué frames on your Mac. Everything runs on your
computer.

------------------------------------------------------------
FIRST TIME SETUP (about 5 minutes, needs internet)
------------------------------------------------------------
1. Unzip StitchKit and move the StitchKit folder somewhere permanent,
   like your Documents folder.
2. Open the Terminal app (Applications > Utilities > Terminal).
3. Type "bash " (with a space after it), drag "Install StitchKit.command"
   from the StitchKit folder into the Terminal window, and press Return.
4. Wait for "StitchKit is installed."

------------------------------------------------------------
UPDATING TO A NEW VERSION
------------------------------------------------------------
1. Quit StitchKit (close its Terminal window).
2. Delete the old StitchKit app folder and put the new one in its place.
3. Run the installer again, the same way as the first time.
Your things are NOT in the app folder, so they are kept: everything lives in
Documents > StitchKit (your made files, Projects, Frames, My threads.txt and
settings.json). The version shows next to the StitchKit name; click it to see
what's new.

------------------------------------------------------------
USING IT
------------------------------------------------------------
Double-click "Open StitchKit.command". StitchKit appears in your web browser.
Leave the Terminal window open while you work; close it to quit.

1. Start with: Artwork (SVG, PNG, JPG), a Stitch file (VP3, PES, DST, JEF...),
   Text, a Monogram, or Arrange files (several stitch files placed by hand).
2. Make a Design, a Patch, or a Frame.
3. Pick sizes, shape or frame, density, copies and file types, then
   "Make stitch files". Files land in Documents > StitchKit.

Inches or millimetres: switch at the top right. Fine stitch widths (border,
spacing, band) are always in millimetres.

------------------------------------------------------------
WHAT YOU GET FOR EACH PIECE
------------------------------------------------------------
- Stitch files (VP3 for your Viking; VIP and others if ticked)
- Preview picture
- Thread sheet (open it in your browser and print): thread order with
  swatches, the closest Poly X40 thread (or your own list), stops, stitch
  counts, size, hoop and sewing time
- Placement template PDF: print at 100% / Actual size. The cross is the
  centre of the design. Measure the 1 inch and 25 mm squares to check.
- Cricut cut file (SVG on a 12 x 12 in mat) whenever there is appliqué
  fabric, including appliqué inside stitch files you bring in. Upload to Design Space and check the size before you cut: Design
  Space sometimes resizes SVGs. Pieces are cut 0.3 mm inside the placement
  line so the tackdown and satin cover the edge.

------------------------------------------------------------
FABRIC AND SUPPLIES (new in 1.2)
------------------------------------------------------------
Pick what you are stitching on (sweatshirt fleece, T-shirt, bandana cotton,
patch twill, towel, canvas, denim or cap). StitchKit sets the density and
pull compensation, adds a knockdown stitch on towels and fleece, and lists
the needle, stabilizer, topping and extras you'll need on screen and on the
thread sheet. Change the supply notes in Settings to match what you use.
- Knockdown thread: pick one that matches your fabric. Until you do, it is
  sewn in the design's first colour, just inside the design.
- Appliqué edges can be satin or blanket stitch.
- Fill stitch for artwork: straight rows, follow the shape, or an open
  meander texture (fabric shows through on purpose).
- Density map: if part of a design is very dense, the result has a map with
  the spots in orange and red.

THREAD BRANDS
Settings > Thread: choose from 70+ built-in charts (Poly X40, Isacord,
Madeira, Sulky, Robison-Anton and more), or Add a thread brand from a chart
saved as text (.txt/.csv/.gpl). Your charts live in Documents > StitchKit >
Threads.

RECENT FILES AND VECTORCRAFT
Recent files are listed under the drop area. For SVG artwork, "Open in
VectorCraft" opens it there; save it (same file) and click "Reload after
saving".

------------------------------------------------------------
HOOPS, COPIES AND STOPS
------------------------------------------------------------
- Hoops: 120 x 120, 260 x 200 and 360 x 200 mm stitching areas, kept 8 mm
  clear of the edge (change this and your usual hoop in Settings). If a piece
  is bigger than your usual hoop, StitchKit asks: use the larger hoop, or
  shrink it to fit.
- Copies: set "Copies in one hooping". StitchKit picks the smallest hoop that
  holds them (10 mm apart) and sews colour by colour: every copy's placement
  line, one stop, every tackdown, one stop, then each thread colour for all
  copies.
- Stops: open "Stitch order and stops" on a result, tick "stop after" on any
  step and click Update files. On a single-needle machine a stop is a pause
  with the same thread.
- Basting box: a running-stitch box sewn first.

------------------------------------------------------------
PATCHES AND FRAMES
------------------------------------------------------------
Patch: the design on a patch shape with a faux-merrow satin border. Fabric is
twill hooped directly, appliqué (placement and tackdown stops), or a stitched
background.

Frame: a decorative frame round the design. Built in: notched and stepped
corners, scroll and bracket labels, scalloped square, cloud, Greek key,
bamboo square and bamboo octagon. Or turn any patch shape into a frame (the
inner line is centred exactly inside the outer at the band width you set).
The band is Appliqué, Fill, or "No fill or applique".
Your own frames: save SVGs in Documents > StitchKit > Frames (outer outline,
and the inner one if you like), then reload StitchKit.

------------------------------------------------------------
MONOGRAMS AND ARRANGING
------------------------------------------------------------
Monogram: type the initials; Classic puts the last-name initial big in the
middle. Embroidery fonts stitch best.
Arrange files: drop several stitch files (for example three monogram letters
saved from Embrilliance), choose a frame or patch and its size, then drag
each file into place. Arrow keys nudge the selected file. Resizing a stitch
file keeps its stitch count, so stay between about 80% and 120%.

------------------------------------------------------------
THREADS
------------------------------------------------------------
Poly X40 is built in. For Exquisite (or any thread), open Settings > Open My
threads list and add one thread per line:  number, name, #rrggbb
then choose "My threads" in Settings.

------------------------------------------------------------
PROJECTS
------------------------------------------------------------
Projects (top right) saves everything on screen, with copies of your files,
in Documents > StitchKit > Projects. Open it again any time.

------------------------------------------------------------
GOOD TO KNOW
------------------------------------------------------------
- Always stitch a test on scrap of the same fabric first.
- VIP files are written by StitchKit itself and have not been tested on a
  machine. VP3 is the one for your Husqvarna Viking.
- StitchKit cannot send files over Wi-Fi to your machine.
- The stitch engine inside is Ink/Stitch (inkstitch.org, GPL-3.0), bundled
  unmodified in the inkstitch_engine folder, with 33 fonts from its font
  library (each font's licence is in its folder). Thread colours for Poly X40
  come from Ink/Stitch's palette files.
- If something fails, the details are saved in ~/.stitchkit/last_error.txt.
