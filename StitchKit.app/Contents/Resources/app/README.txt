STITCHKIT 1.3 beta
Digitize artwork, make patches, frames and bag tags on your Mac. Everything runs on your computer.

------------------------------------------------------------
INSTALLING (the first time, or updating from 1.2)
------------------------------------------------------------
1. Double-click StitchKit-1.3.zip to unzip it. Drag StitchKit (the app with the raspberry S)
   into your Applications folder.
2. Double-click StitchKit in Applications.
   macOS will say it can't check the app for malicious software (it isn't from the App Store).
   Click Done, then open System Settings > Privacy & Security, scroll down and click
   "Open Anyway" next to StitchKit, then "Open Anyway" again. You only do this once.
3. The first time, a "Setting up StitchKit" page opens while it fetches its parts
   (about five minutes, needs the internet). StitchKit then opens in your browser.
After that, just double-click StitchKit (put it in your Dock if you like). It quits by itself a
while after you close its browser tab, or use Settings > Quit StitchKit.

Coming from 1.2: you no longer need the old StitchKit folder or Terminal. If that folder was
Documents > StitchKit itself, StitchKit 1.3 moves the old program files into
"Old StitchKit app (safe to delete)" in there; your files, frames and projects are not touched.
Otherwise drag the old StitchKit folder to the Trash.

Your things are never inside the app, so updating is just replacing the app:
Documents > StitchKit holds your made files, Projects, Frames, Bag Tags, Monogram Fonts,
Threads, My threads.txt and settings.json.

------------------------------------------------------------
USING IT (one screen)
------------------------------------------------------------
Left:   1. What are you making?  Design, Patch, Frame or Bag tag.
        2. What goes on it?      Artwork (SVG, PNG, JPG), a Stitch file, Words, a Monogram,
                                 Arrange (several things placed by hand), or Nothing (tags and
                                 your own frame files).
Middle: the live preview: the real stitches, on a grid inside your hoop. Zoom with the + and -
        buttons or by scrolling; the colour square sets the fabric colour.
        Shapes (for artwork): click a shape to change it. Arrange: drag pieces into place.
Right:  shape, size, edges, fabric and supplies, stitching, hooping and file types.
        "Make stitch files" saves everything in Documents > StitchKit.

Inches or millimetres: top right. Fine widths (border, spacing, band) are in millimetres.

------------------------------------------------------------
BAG TAGS
------------------------------------------------------------
Pick a tag shape (or one of your tag files), its size, the keyring hole and what goes in the
middle (3 mm embroidery foam or Peltex I 71F). The machine stops at each layer:
  placement line > lay front cotton > tack line > your design > STOP: hoop off, turn it over,
  foam + back cotton > tackdown > STOP: trim > dense satin edge and keyring hole.
"How to make it" (on screen and on the thread sheet) walks you through every step, including
popping it out, punching the hole and tidying foam edges with a lighter.

------------------------------------------------------------
YOUR OWN FRAMES, TAGS AND MONOGRAM LETTERS
------------------------------------------------------------
Frames     Documents > StitchKit > Frames: stitch files of frames you own (VP3, PES, DST...).
           Sizes in the name are grouped: Wreath_4in.vp3 and Wreath_5in.vp3 become one frame
           in two sizes. Frames saved as two halves: put both in a folder, named ..._left and
           ..._right (or L and R); StitchKit sets them either side of your design.
           Your design is sewn after the frame's tackdown and before its final satin (change it
           under "Your design sews"). The frame's own stitches are never changed.
           SVG outlines in this folder still work as frames StitchKit digitizes itself.
Bag tags   Documents > StitchKit > Bag Tags (files in Frames with "tag" in the name show too).
           StitchKit finds the placement line, tackdown and satin and adds the stops; if a file
           has no tack line for the front cotton, it adds one.
Monograms  Documents > StitchKit > Monogram Fonts, plus any folders you add in Settings
           (for example your existing Monograms > vp3 folder). Any folder of letter files
           (A.vp3 ... Z.vp3, or names ending in the letter like Blair_13QA.vp3) is a set.
           The folder name gives the font and size: WesternShadow1 = 1 in,
           WesternShadow1H = 1.5 in, WesternShadow2H = 2.5 in, Script 38mm = 38 mm.
           Choose the font by its letter M. "Biggest that fits" picks the size for your patch,
           frame or tag. Classic monograms use a smaller size of the same font for the side
           letters.
Click "Reload" in your browser after adding files.

------------------------------------------------------------
CHANGE SHAPES (artwork)
------------------------------------------------------------
Click Shapes above the preview (or "Change shapes..."). Click a shape, shift-click for more:
change its thread, its stitches (straight rows, follow the shape, open texture, outline only,
or leave it out), the direction of the rows, join it to another shape, or make it appliqué
with a satin or blanket edge. Every change shows in the live preview.

------------------------------------------------------------
ARRANGE
------------------------------------------------------------
Drop stitch files, or press + Words, + Monogram or + Artwork. Drag pieces in the preview;
arrow keys nudge (shift for bigger steps), Delete removes. Shift-click to pick several, then
line them up: left, centre or right edges, tops, middles or bottoms, centre in the hoop, or
space three or more evenly. Pieces snap to each other's edges and centres.

------------------------------------------------------------
WHAT YOU GET FOR EACH PIECE
------------------------------------------------------------
- Stitch files (VP3 for your Viking; VIP and others if ticked)
- Preview picture
- Thread sheet to print: thread order with your brand's closest threads, stops, what you will
  need, sewing time and, for bag tags, the step-by-step guide
- Placement template PDF: print at 100% / Actual size and measure the check squares
- Cricut cut file (SVG on a 12 x 12 in mat) whenever there is appliqué fabric. Check the size in
  Design Space before cutting.

------------------------------------------------------------
GOOD TO KNOW
------------------------------------------------------------
- Always stitch a test on scrap of the same fabric first.
- VIP files are written by StitchKit itself and have not been tested on a machine. VP3 is the one
  for your Husqvarna Viking.
- StitchKit cannot send files over Wi-Fi to your machine.
- The stitch engine inside is Ink/Stitch (inkstitch.org, GPL-3.0), bundled unmodified, with 33
  fonts from its font library (each font's licence is in its folder).
- If something goes wrong, the details are saved in ~/.stitchkit/last_error.txt, and the setup
  log is in Library > Application Support > StitchKit > setup.log.
