// Builds "Dyno, Sage & Penny" — the Gemma Hardware Hackathon deck.
// Run from deck/:  node build_deck.js   (writes ../dyno-sage-penny-deck.pptx)
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");
const gi = require("react-icons/gi");
const md = require("react-icons/md");
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const OUT = path.join(__dirname, "..", "dyno-sage-penny-deck.pptx");
const IMG = (f) => path.join(__dirname, "img", f);

// ---------- theme: night sky + starlight, one color per character ----------
const THEME = {
  name: "Starlight",
  headFontFace: "Century Schoolbook",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1B1F4B",   // night-sky navy (dominant)
    lt1: "FFFFFF",
    dk2: "4A4F7A",   // muted navy for secondary text
    lt2: "F1F0FA",   // faint lavender tint for panels
    accent1: "F5C542", // starlight gold
    accent2: "3E8E2F", // Dyno green
    accent3: "E2711D", // Sage orange (giraffe-unicorn suit)
    accent4: "2F6FC9", // Penny blue
    accent5: "F7E7B4", // pale gold
    accent6: "8B8FB0", // soft gray-violet
    hlink: "2F6FC9",
    folHlink: "4A4F7A",
  },
};
const HEX = THEME.colors;

// ---------- icons ----------
async function icon(Comp, hex, size = 256) {
  let svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { size }));
  svg = svg.replace(/currentColor/g, "#" + hex);
  const buf = await sharp(Buffer.from(svg)).resize(size, size).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}
const pick = (lib, ...names) => {
  for (const n of names) if (lib[n]) return lib[n];
  throw new Error("missing icon " + names.join("/"));
};

// deterministic "stars" for dark layouts
function stars(seed, n) {
  let s = seed;
  const rnd = () => ((s = (s * 9301 + 49297) % 233280) / 233280);
  const out = [];
  for (let i = 0; i < n; i++) {
    const x = rnd() * 13.2, y = rnd() * 7.4, r = 0.03 + rnd() * 0.06;
    // keep the star field around the edges so it never fights the text
    if (x > 0.4 && x < 12.9 && y > 0.9 && y < 6.6 && rnd() > 0.25) continue;
    out.push({ ellipse: { x, y, w: r, h: r, fill: { color: "FFFFFF", transparency: 25 + Math.floor(rnd() * 55) },
                          line: { type: "none" } } });
  }
  return out;
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
  pres.title = "Dyno, Sage & Penny";
  pres.author = "Patrick Hanley";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  const C = pres.SchemeColor;
  const FOOT = "Dyno, Sage & Penny  ·  Gemma Hardware Hackathon, AGI House  ·  Oct 24, 2026";

  // ---------- layouts ----------
  pres.defineSlideMaster({
    title: "TITLE_DARK",
    background: { color: C.text1 },
    objects: stars(7, 70),
    slideNumber: undefined,
  });
  pres.defineSlideMaster({
    title: "CONTENT",
    background: { color: C.background1 },
    margin: [0.5, 0.6, 0.6, 0.6],
    objects: [
      { placeholder: { options: { name: "kicker", type: "body", x: 0.6, y: 0.32, w: 12.1, h: 0.36, fontSize: 12,
          bold: true, color: C.text2, charSpacing: 2, valign: "middle", margin: 0 }, text: "" } },
      { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.66, w: 12.1, h: 0.85, fontSize: 36,
          bold: true, color: C.text1, align: "left", valign: "middle", margin: 0 }, text: "" } },
      { text: { text: FOOT, options: { x: 0.6, y: 7.0, w: 9, h: 0.3, fontSize: 10, color: C.accent6, margin: 0 } } },
    ],
    slideNumber: { x: 12.3, y: 7.0, w: 0.45, h: 0.3, fontSize: 10, color: C.accent6, align: "right" },
  });
  pres.defineSlideMaster({
    title: "CONTENT_DARK",
    background: { color: C.text1 },
    objects: [
      ...stars(23, 70),
      { placeholder: { options: { name: "kicker", type: "body", x: 0.6, y: 0.32, w: 12.1, h: 0.36, fontSize: 12,
          bold: true, color: C.accent1, charSpacing: 2, valign: "middle", margin: 0 }, text: "" } },
      { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.66, w: 12.1, h: 0.85, fontSize: 36,
          bold: true, color: C.background1, align: "left", valign: "middle", margin: 0 }, text: "" } },
      { text: { text: FOOT, options: { x: 0.6, y: 7.0, w: 9, h: 0.3, fontSize: 10, color: C.accent6, margin: 0 } } },
    ],
    slideNumber: { x: 12.3, y: 7.0, w: 0.45, h: 0.3, fontSize: 10, color: C.accent6, align: "right" },
  });

  // ---------- icon set ----------
  const I = {
    dino: await icon(pick(gi, "GiDinosaurRex"), "FFFFFF"),
    unicorn: await icon(pick(gi, "GiUnicorn"), "FFFFFF"),
    penguin: await icon(pick(gi, "GiPenguin"), "FFFFFF"),
    star: await icon(fa.FaStar, HEX.accent1),
    starNavy: await icon(fa.FaStar, HEX.dk1),
    book: await icon(fa.FaBook, "FFFFFF"),
    clock: await icon(fa.FaClock, "FFFFFF"),
    magic: await icon(pick(fa, "FaMagic", "FaWandMagicSparkles"), "FFFFFF"),
    bulb: await icon(fa.FaLightbulb, "FFFFFF"),
    cap: await icon(fa.FaGraduationCap, "FFFFFF"),
    camera: await icon(fa.FaCamera, "FFFFFF"),
    mic: await icon(fa.FaMicrophone, "FFFFFF"),
    speaker: await icon(fa.FaVolumeUp, "FFFFFF"),
    wifi: await icon(fa.FaWifi, HEX.dk1),
    ear: await icon(pick(md, "MdHearing"), "FFFFFF"),
    eye: await icon(fa.FaEye, "FFFFFF"),
    brain: await icon(fa.FaBrain, "FFFFFF"),
    chat: await icon(fa.FaCommentDots, "FFFFFF"),
    child: await icon(fa.FaChild, "FFFFFF"),
    family: await icon(fa.FaUserFriends, "FFFFFF"),
    tag: await icon(fa.FaTag, "FFFFFF"),
    paw: await icon(fa.FaPaw, "FFFFFF"),
    cloudOff: await icon(pick(md, "MdCloudOff"), "FFFFFF"),
    trash: await icon(fa.FaTrashAlt, "FFFFFF"),
    school: await icon(pick(md, "MdSchool"), "FFFFFF"),
    hint: await icon(fa.FaPuzzlePiece, "FFFFFF"),
    heart: await icon(fa.FaHeart, "FFFFFF"),
    lock: await icon(fa.FaLock, "FFFFFF"),
    bolt: await icon(fa.FaBolt, "FFFFFF"),
    cubes: await icon(fa.FaCubes, "FFFFFF"),
    hand: await icon(pick(fa, "FaHandPaper", "FaHand"), "FFFFFF"),
    github: await icon(fa.FaGithub, "FFFFFF"),
    bug: await icon(fa.FaBug, "FFFFFF"),
  };
  const CHAR = {
    dyno: { name: "Dyno", color: C.accent2, hex: HEX.accent2, tint: "E6F1E2", icon: I.dino },
    sage: { name: "Sage", color: C.accent3, hex: HEX.accent3, tint: "FCEADB", icon: I.unicorn },
    penny: { name: "Penny", color: C.accent4, hex: HEX.accent4, tint: "E2EBF8", icon: I.penguin },
  };
  // icon in a filled circle — the deck's motif
  const badge = (slide, data, x, y, d, fill, name, pad = 0.22) => {
    slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: { type: "none" }, objectName: name + " circle" });
    slide.addImage({ data, x: x + d * pad, y: y + d * pad, w: d * (1 - 2 * pad), h: d * (1 - 2 * pad), objectName: name + " icon" });
  };
  const shadow = () => ({ type: "outer", color: "1B1F4B", blur: 8, offset: 2, angle: 90, opacity: 0.14 });

  // =====================================================================
  // 1. Title
  pres.addSection({ title: "Once upon a time" });
  {
    const s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Once upon a time" });
    s.addText("GEMMA HARDWARE HACKATHON  ·  PHYSICAL AI, IoT & ROBOTICS", { x: 0.7, y: 0.9, w: 6.6, h: 0.4,
      fontSize: 13, bold: true, color: C.accent1, charSpacing: 2, margin: 0, isTextBox: true });
    s.addText("Dyno, Sage & Penny", { x: 0.7, y: 1.45, w: 6.6, h: 1.9, fontSize: 54, bold: true,
      fontFace: THEME.headFontFace, color: C.background1, margin: 0, valign: "top", isTextBox: true });
    s.addText("Three plush friends who see you, listen, and learn with you. Powered by Gemma, entirely in the room.",
      { x: 0.7, y: 3.4, w: 6.2, h: 1.2, fontSize: 20, color: "D9DAF0", margin: 0, valign: "top", isTextBox: true });
    // cast chips
    ["dyno", "sage", "penny"].forEach((k, i) => {
      const x = 0.7 + i * 2.05;
      badge(s, CHAR[k].icon, x, 5.05, 0.62, CHAR[k].color, CHAR[k].name);
      s.addText(CHAR[k].name, { x: x + 0.72, y: 5.05, w: 1.25, h: 0.62, fontSize: 17, bold: true, color: C.background1,
        valign: "middle", margin: 0, isTextBox: true });
    });
    s.addText("No cloud anywhere in the loop.", { x: 0.7, y: 6.15, w: 6.2, h: 0.4, fontSize: 14, italic: true,
      color: C.accent1, margin: 0, isTextBox: true });
    // hero: the real cast on a white "stage" card
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 7.45, y: 0.75, w: 5.25, h: 5.95, rectRadius: 0.25,
      fill: { color: C.background1 }, line: { type: "none" }, shadow: { type: "outer", color: "000000", blur: 18, offset: 4, angle: 90, opacity: 0.35 },
      objectName: "hero stage" });
    s.addImage({ path: IMG("ref_image1.jpg"), x: 7.65, y: 1.0, w: 4.85, h: 4.55, altText: "Penny the penguin, Sage the baby unicorn and Dyno the dinosaur, each with an Atom camera on its forehead", objectName: "cast photo" });
    s.addText("The real cast. Each forehead holds a camera, mic and speaker.", { x: 7.75, y: 5.75, w: 4.65, h: 0.7,
      fontSize: 12, italic: true, color: C.text2, align: "center", valign: "middle", margin: 0, isTextBox: true });
    s.addNotes("Hi! Meet Dyno, Sage and Penny. They're three plush friends who can see who's in front of them, hear a child without anyone pressing a button, and talk back in their own voices. All of it runs on a computer at the table, with no cloud. Disney would start with the characters, not the chips, so that's what we'll do.");
  }

  // 2. Story spine
  {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Once upon a time" });
    s.addText("THE STORY  ·  PIXAR'S STORY SPINE", { placeholder: "kicker" });
    s.addText("Once upon a time, homework was lonely", { placeholder: "title" });
    const beats = [
      ["Once upon a time…", "a third grader sat alone with a worksheet and a screen.", I.book],
      ["Every day…", "asking for help felt harder than guessing.", I.clock],
      ["One day…", "three plush friends sat down at the table, and they could see and hear.", I.magic],
      ["Because of that…", "the child got to ask questions, explain answers, and teach a curious dinosaur.", I.bulb],
      ["Until finally…", "homework felt like playing with friends, and the child became the teacher.", I.cap],
    ];
    beats.forEach(([lead, rest, ic], i) => {
      const y = 1.85 + i * 0.98;
      badge(s, ic, 0.75, y, 0.72, i === 2 ? C.accent1 : C.text1, "beat " + (i + 1));
      s.addText([{ text: lead + " ", options: { bold: true, color: C.text1 } }, { text: rest, options: { color: C.text2 } }],
        { x: 1.75, y, w: 10.8, h: 0.72, fontSize: 20, valign: "middle", margin: 0, isTextBox: true, objectName: "beat text " + (i + 1) });
    });
    s.addNotes("Pixar plans every film with a story spine, so here's ours. Homework time is often a kid alone with a worksheet, and asking for help can feel harder than guessing. One day three plush friends sit down at the table with them. Because of that, the child gets to ask questions, explain answers, and teach a curious dinosaur. Until finally, the child is the one teaching. That last beat is the heart of the whole project.");
  }

  // 3. Meet the cast
  pres.addSection({ title: "The characters" });
  {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "The characters" });
    s.addText("MEET THE CAST", { placeholder: "kicker" });
    s.addText("Same hardware, three different hearts", { placeholder: "title" });
    const cards = [
      ["dyno", "a green dinosaur", "The curious one", "Asks the questions a shy kid might not.", "“Rawr! What's that?”"],
      ["sage", "a baby in a unicorn suit", "The careful one", "Reads, explains, and gives hints, never just the answer.", "“Let's figure it out together.”"],
      ["penny", "a penguin in a woolly hat", "The imaginative one", "Turns right answers into wordplay and make-believe.", "“Imagine numbers in party hats!”"],
    ];
    cards.forEach(([k, looks, role, does, quote], i) => {
      const x = 0.6 + i * 4.1, w = 3.85, ch = CHAR[k];
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.85, w, h: 4.4, rectRadius: 0.2, fill: { color: ch.tint },
        line: { type: "none" }, shadow: shadow(), objectName: ch.name + " card" });
      badge(s, ch.icon, x + 0.35, 2.15, 1.05, ch.color, ch.name);
      s.addText(ch.name, { x: x + 1.6, y: 2.15, w: w - 1.8, h: 0.62, fontSize: 30, bold: true, fontFace: THEME.headFontFace,
        color: ch.color, valign: "middle", margin: 0, isTextBox: true });
      s.addText(looks, { x: x + 1.6, y: 2.75, w: w - 1.8, h: 0.45, fontSize: 14, color: C.text2, valign: "top", margin: 0, isTextBox: true });
      s.addText(role, { x: x + 0.35, y: 3.5, w: w - 0.7, h: 0.45, fontSize: 18, bold: true, color: C.text1, margin: 0, isTextBox: true });
      s.addText(does, { x: x + 0.35, y: 3.95, w: w - 0.7, h: 1.1, fontSize: 16, color: C.text1, valign: "top", margin: 0, isTextBox: true });
      s.addText(quote, { x: x + 0.35, y: 5.15, w: w - 0.7, h: 0.8, fontSize: 18, italic: true, fontFace: THEME.headFontFace,
        color: ch.color, valign: "top", margin: 0, isTextBox: true });
    });
    s.addNotes("Every toy has identical hardware: a camera, a mic and a speaker on an ESP32 board. What makes them different is character. Dyno is curious and asks the questions a shy kid might not. Sage is careful: she reads, explains, and gives hints instead of answers. Penny is the imaginative one: she always gets the facts right, then turns them into wordplay and make-believe.");
  }

  // 4. The magic moment
  {
    const s = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "The characters" });
    s.addText("THE MAGIC MOMENT", { placeholder: "kicker" });
    s.addText("The child becomes the teacher", { placeholder: "title" });
    const lines = [
      ["dyno", "Rawr! What's seven times eight? Can you teach me?"],
      ["child", "It's fifty-six! Seven groups of eight."],
      ["sage", "That's right, and you explained it perfectly."],
      ["penny", "Fifty-six! I imagine seven rows of eight penguins!"],
      ["dyno", "Rawr! You're a great teacher!"],
    ];
    lines.forEach(([who, text], i) => {
      const y = 1.8 + i * 0.98, isChild = who === "child";
      const w = 5.6, x = isChild ? 0.7 : 2.4;
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 0.78, rectRadius: 0.2,
        fill: { color: isChild ? C.background1 : CHAR[who].color }, line: { type: "none" }, objectName: "bubble " + (i + 1) });
      s.addText([{ text: (isChild ? "Child" : CHAR[who].name) + ":  ", options: { bold: true } }, { text }],
        { x: x + 0.25, y, w: w - 0.5, h: 0.78, fontSize: 18, color: isChild ? C.text1 : C.background1, valign: "middle",
          margin: 0, isTextBox: true });
      if (!isChild) badge(s, CHAR[who].icon, x - 0.95, y + 0.02, 0.74, CHAR[who].color, CHAR[who].name + " " + i);
    });
    // spotlight callout
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 8.7, y: 1.8, w: 4.0, h: 4.7, rectRadius: 0.2, fill: { color: "2A2F66" },
      line: { color: C.accent1, width: 1.5 }, objectName: "spotlight card" });
    s.addImage({ data: I.star, x: 10.35, y: 2.1, w: 0.7, h: 0.7, objectName: "spotlight star" });
    s.addText("Being right is nice.\nBeing the one who explains is magic.", { x: 9.0, y: 2.95, w: 3.4, h: 1.6, fontSize: 20,
      bold: true, fontFace: THEME.headFontFace, color: C.background1, align: "center", valign: "middle", margin: 0, isTextBox: true });
    s.addText("Dyno's curiosity hands the child the chalk. Gemma writes every line, and the facts always stay right.",
      { x: 9.0, y: 4.65, w: 3.4, h: 1.6, fontSize: 14, color: "D9DAF0", align: "center", valign: "top", margin: 0, isTextBox: true });
    s.addNotes("Here's the moment we built everything around. Dyno is curious, so instead of lecturing, Dyno asks the child to teach him seven times eight. The child explains it, Sage confirms it, and Penny adds her imaginative twist: seven rows of eight penguins. Every line comes from Gemma, and the facts stay right. Disney would call this the emotional beat: the child gets to be the expert in the room.");
  }

  // 5. They know who's in the room
  {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "The characters" });
    s.addText("EYES THAT KNOW YOU", { placeholder: "kicker" });
    s.addText("Every toy knows who it's looking at", { placeholder: "title" });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 1.85, w: 5.7, h: 4.85, rectRadius: 0.2, fill: { color: C.background2 },
      line: { type: "none" }, objectName: "camera panel" });
    s.addImage({ path: IMG("dyno_view_earlier.jpg"), x: 0.85, y: 2.1, w: 5.2, h: 3.9, altText: "Real 320 by 240 frame from Dyno's camera showing Penny's woolly hat up close", objectName: "dyno camera frame" });
    s.addText("A real frame from Dyno's camera: Penny's woolly hat, up close (320 × 240).", { x: 0.85, y: 6.05, w: 5.2, h: 0.5,
      fontSize: 12, italic: true, color: C.text2, margin: 0, valign: "middle", isTextBox: true });
    const rows = [
      [I.child, C.text1, "The child", "Any face it doesn't know becomes “the child” it's playing with."],
      [I.family, C.accent3, "Family", "Faces enrolled from a few photos, greeted by name."],
      [I.tag, C.accent2, "Each other", "A tag on each toy's chest, so Dyno can tell Penny from Sage."],
      [I.paw, C.accent4, "Pets and books", "A LiteRT object detector (Pi and Jetson build) spots dogs, cats and books."],
    ];
    rows.forEach(([ic, col, head, body], i) => {
      const y = 1.9 + i * 1.18;
      badge(s, ic, 6.75, y, 0.78, col, head);
      s.addText(head, { x: 7.75, y: y - 0.02, w: 4.95, h: 0.4, fontSize: 18, bold: true, color: C.text1, margin: 0, isTextBox: true });
      s.addText(body, { x: 7.75, y: y + 0.38, w: 4.95, h: 0.7, fontSize: 15, color: C.text2, valign: "top", margin: 0, isTextBox: true });
    });
    s.addNotes("Each toy's camera tells it who's there. An unknown face is the child it's playing with. Family members get recognized from a few enrolled photos and greeted by name. The toys recognize each other by a tag on their chests. Pets and books come from an object detector built for LiteRT on the Pi or Jetson build. Whatever is biggest and most centered is what a toy is 'looking at'. This photo is a real frame from Dyno's camera, looking at Penny's woolly hat.");
  }

  // 6. Behind the curtain
  pres.addSection({ title: "Behind the curtain" });
  {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Behind the curtain" });
    s.addText("BEHIND THE CURTAIN", { placeholder: "kicker" });
    s.addText("Thin toys, one brain at the table", { placeholder: "title" });
    // toy box
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 2.0, w: 2.5, h: 3.1, rectRadius: 0.2, fill: { color: C.text1 },
      line: { type: "none" }, shadow: shadow(), objectName: "toy box" });
    s.addText("Each toy", { x: 0.75, y: 2.15, w: 2.2, h: 0.5, fontSize: 20, bold: true, color: C.background1, align: "center", margin: 0, isTextBox: true });
    [[I.camera, "camera"], [I.mic, "mic"], [I.speaker, "speaker"]].forEach(([ic, lab], i) => {
      const y = 2.75 + i * 0.68;
      s.addImage({ data: ic, x: 0.95, y, w: 0.42, h: 0.42, objectName: lab + " icon" });
      s.addText(lab, { x: 1.55, y, w: 1.4, h: 0.42, fontSize: 16, color: C.background1, valign: "middle", margin: 0, isTextBox: true });
    });
    s.addText("ESP32-S3 Atom", { x: 0.75, y: 4.7, w: 2.2, h: 0.3, fontSize: 12, color: C.accent5, align: "center", margin: 0, isTextBox: true });
    // wifi link
    s.addShape(pres.shapes.LINE, { x: 3.2, y: 3.0, w: 0.95, h: 0, line: { color: C.text1, width: 2.5, endArrowType: "triangle" }, objectName: "to brain" });
    s.addImage({ data: I.wifi, x: 3.47, y: 3.25, w: 0.42, h: 0.42, objectName: "wifi icon" });
    s.addText("Wi-Fi\n7.6 ms", { x: 3.15, y: 3.7, w: 1.05, h: 0.6, fontSize: 12, color: C.text2, align: "center", margin: 0, isTextBox: true });
    // brain region
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 4.3, y: 1.75, w: 8.4, h: 3.6, rectRadius: 0.2, fill: { color: C.background2 },
      line: { type: "none" }, objectName: "brain region" });
    s.addText("The brain, on the table", { x: 4.5, y: 1.85, w: 8, h: 0.42, fontSize: 16, bold: true, color: C.text1, margin: 0, isTextBox: true });
    const stages = [
      [I.ear, C.accent4, "Listen", "Hears a voice start and stop, no button."],
      [I.eye, C.accent3, "See", "Faces, tags, pets and books."],
      [I.brain, C.text1, "Think", "Gemma 4 E2B writes every line."],
      [I.chat, C.accent2, "Speak", "Piper gives each toy its own voice."],
    ];
    stages.forEach(([ic, col, head, body], i) => {
      const x = 4.5 + i * 2.05;
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 2.4, w: 1.9, h: 2.75, rectRadius: 0.15, fill: { color: C.background1 },
        line: { type: "none" }, shadow: shadow(), objectName: head + " card" });
      badge(s, ic, x + 0.55, 2.6, 0.8, col, head);
      s.addText(head, { x: x + 0.1, y: 3.5, w: 1.7, h: 0.42, fontSize: 18, bold: true, color: C.text1, align: "center", margin: 0, isTextBox: true });
      s.addText(body, { x: x + 0.12, y: 3.95, w: 1.66, h: 1.1, fontSize: 13, color: C.text2, align: "center", valign: "top", margin: 0, isTextBox: true });
    });
    // return path
    s.addShape(pres.shapes.LINE, { x: 1.85, y: 5.75, w: 8.6, h: 0, line: { color: C.accent2, width: 2.5 }, objectName: "speech back" });
    s.addShape(pres.shapes.LINE, { x: 10.45, y: 5.35, w: 0, h: 0.4, line: { color: C.accent2, width: 2.5 }, objectName: "speech back riser" });
    s.addShape(pres.shapes.LINE, { x: 1.85, y: 5.15, w: 0, h: 0.6, line: { color: C.accent2, width: 2.5, beginArrowType: "triangle" }, objectName: "speech back into toy" });
    s.addText("each line of speech reaches its toy in about 0.2 s", { x: 3.0, y: 5.8, w: 6.5, h: 0.4, fontSize: 14, bold: true,
      color: C.accent2, align: "center", margin: 0, isTextBox: true });
    s.addText("Today: Gemma via llama.cpp with Whisper on an Intel Mac. Ready to run: a LiteRT-LM build for Raspberry Pi 5 and Jetson, where Gemma hears the audio directly.",
      { x: 0.6, y: 6.3, w: 12.1, h: 0.55, fontSize: 13, italic: true, color: C.text2, margin: 0, valign: "top", isTextBox: true });
    s.addNotes("Behind the curtain, the toys are deliberately thin. They only sense and speak. Each Atom streams its mic and answers camera requests over a local Wi-Fi hotspot with about 8 milliseconds of round trip. The brain listens for when a child starts and stops talking, looks through all three cameras, asks Gemma what each toy should say, and voices it with Piper. To be precise about today: on this Intel Mac, Gemma runs through llama.cpp with Whisper for speech. The LiteRT-LM build for a Pi 5 or Jetson is written and packed, and on those devices Gemma hears the audio directly.");
  }

  // 7. Why the brain is outside the toy
  {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Behind the curtain" });
    s.addText("WHY THE BRAIN LIVES OUTSIDE THE TOY", { placeholder: "kicker" });
    s.addText("It's arithmetic, not a preference", { placeholder: "title" });
    const stat = (x, num, lab, col) => {
      s.addText(num, { x, y: 2.05, w: 3.6, h: 1.4, fontSize: 66, bold: true, fontFace: THEME.headFontFace, color: col, align: "center", margin: 0, isTextBox: true });
      s.addText(lab, { x, y: 3.45, w: 3.6, h: 0.7, fontSize: 16, color: C.text2, align: "center", valign: "top", margin: 0, isTextBox: true });
    };
    stat(0.7, "2.6 GB", "Gemma 4 E2B model file", C.text1);
    s.addText("÷", { x: 4.35, y: 2.05, w: 0.8, h: 1.4, fontSize: 54, color: C.accent6, align: "center", margin: 0, isTextBox: true });
    stat(4.85, "8 MB", "memory inside each toy", C.accent3);
    s.addText("=", { x: 8.5, y: 2.05, w: 0.8, h: 1.4, fontSize: 54, color: C.accent6, align: "center", margin: 0, isTextBox: true });
    stat(9.0, "~320×", "too big to fit", C.accent4);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 1.6, y: 4.65, w: 10.1, h: 1.75, rectRadius: 0.2, fill: { color: C.background2 },
      line: { type: "none" }, objectName: "quote card" });
    badge(s, I.heart, 2.0, 5.07, 0.9, C.accent3, "heart");
    s.addText("The toy keeps what it's good at: being hugged.\nThe brain does what it's good at: thinking.", { x: 3.2, y: 4.8, w: 8.2, h: 1.45,
      fontSize: 22, italic: true, fontFace: THEME.headFontFace, color: C.text1, valign: "middle", margin: 0, isTextBox: true });
    s.addNotes("Why not put Gemma inside the toy? The Gemma 4 E2B model file is about 2.6 gigabytes. The ESP32 inside each toy has 8 megabytes of memory. That's roughly 320 times too small. So the toy keeps what it's good at, being soft and huggable, and the brain at the table does the thinking.");
  }

  // 8. Plussing
  {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Behind the curtain" });
    s.addText("PLUSSING: WALT'S WORD FOR MAKING IT BETTER, AGAIN AND AGAIN", { placeholder: "kicker" });
    s.addText("We kept plussing it", { placeholder: "title" });
    s.addChart(pres.charts.BAR, [{ name: "Network delay", labels: ["Raw audio, phone hotspot", "Compressed audio, phone hotspot", "Compressed audio, Mac hotspot"], values: [11.5, 3.1, 0.2] }], {
      x: 0.6, y: 1.8, w: 6.6, h: 4.6, barDir: "bar", chartColors: [HEX.accent2],
      showTitle: true, title: "Wait before a toy starts talking (seconds)", titleFontSize: 15, titleColor: HEX.dk1, titleFontFace: "+mn-lt",
      showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 14, dataLabelColor: HEX.dk1, dataLabelFormatCode: '0.0" s"', dataLabelFontFace: "+mn-lt",
      catAxisLabelColor: HEX.dk2, catAxisLabelFontSize: 13, catAxisLabelFontFace: "+mn-lt", catAxisOrientation: "maxMin",
      valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" }, showLegend: false, barGapWidthPct: 60,
      objectName: "delay chart",
    });
    s.addText("Three mysteries solved", { x: 7.65, y: 1.8, w: 5.05, h: 0.45, fontSize: 18, bold: true, color: C.text1, margin: 0, isTextBox: true });
    const mysteries = [
      ["The silent mic", "The sound chip spoke in the other stereo channel, so every mic heard nothing."],
      ["The camera that couldn't JPEG", "This sensor has no JPEG encoder, so each toy compresses its own pictures."],
      ["Three toys, one name", "Every board reported the same ID, so the brain thought all three were Dyno."],
    ];
    mysteries.forEach(([head, body], i) => {
      const y = 2.4 + i * 1.35;
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 7.65, y, w: 5.05, h: 1.18, rectRadius: 0.15, fill: { color: C.background2 },
        line: { type: "none" }, objectName: "mystery " + (i + 1) });
      badge(s, I.bug, 7.85, y + 0.24, 0.7, [C.accent4, C.accent3, C.accent2][i], "mystery " + (i + 1));
      s.addText(head, { x: 8.75, y: y + 0.1, w: 3.8, h: 0.4, fontSize: 16, bold: true, color: C.text1, margin: 0, isTextBox: true });
      s.addText(body, { x: 8.75, y: y + 0.48, w: 3.8, h: 0.65, fontSize: 13, color: C.text2, valign: "top", margin: 0, isTextBox: true });
    });
    s.addNotes("Walt Disney called it plussing: always making the thing a little better. Our first version made a child wait over eleven seconds just for a toy's voice to arrive. Compressing the audio got that to about three, and hosting the Wi-Fi on the Mac got it to a fifth of a second. Along the way we solved three hardware mysteries: a mic that heard nothing because the sound chip talked in the other stereo channel, a camera with no JPEG encoder, and three boards that all claimed the same ID.");
  }

  // 9. Trust
  pres.addSection({ title: "Happily ever after" });
  {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Happily ever after" });
    s.addText("BUILT FOR A PARENT'S TRUST", { placeholder: "kicker" });
    s.addText("Magic that stays in the room", { placeholder: "title" });
    const tiles = [
      [I.cloudOff, C.text1, "Nothing leaves the room", "No cloud, ever. The toys talk to a computer on the table over local Wi-Fi."],
      [I.trash, C.accent4, "No recordings kept", "Speech lives in memory and is deleted as soon as Gemma has heard it."],
      [I.school, C.accent2, "School-day topics", "Subjects, homework, toys and games. Off-topic chat gets kindly steered back."],
      [I.hint, C.accent3, "Hints, not answers", "Homework help that keeps the child thinking."],
      [I.heart, C.accent3, "Feelings first", "A sad child hears kindness, and a nudge to tell a grown-up they trust."],
      [I.lock, C.text1, "Family data on a leash", "Enrolled faces stay on the brain and are wiped with one command."],
    ];
    tiles.forEach(([ic, col, head, body], i) => {
      const x = 0.6 + (i % 3) * 4.1, y = 1.85 + Math.floor(i / 3) * 2.45;
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 3.85, h: 2.2, rectRadius: 0.15, fill: { color: C.background1 },
        line: { color: "E3E2F0", width: 1 }, shadow: shadow(), objectName: head + " tile" });
      badge(s, ic, x + 0.3, y + 0.3, 0.75, col, head);
      s.addText(head, { x: x + 1.2, y: y + 0.3, w: 2.5, h: 0.75, fontSize: 17, bold: true, color: C.text1, valign: "middle", margin: 0, isTextBox: true });
      s.addText(body, { x: x + 0.3, y: y + 1.2, w: 3.3, h: 0.9, fontSize: 14, color: C.text2, valign: "top", margin: 0, isTextBox: true });
    });
    s.addNotes("Disney parks run on trust, and so should a toy that listens to a child. Nothing leaves the room. Speech is kept in memory only until Gemma hears it, then deleted. The toys stick to school subjects, homework, toys and games, and steer other topics back kindly. They give hints instead of answers. If a child sounds sad, kindness comes first, along with a suggestion to tell a grown-up they trust. Enrolled family faces never leave the brain and can be wiped with one command.");
  }

  // 10. What's next / thank you
  {
    const s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Happily ever after" });
    s.addText("TO BE CONTINUED", { x: 0.7, y: 0.75, w: 6, h: 0.4, fontSize: 13, bold: true, color: C.accent1, charSpacing: 2, margin: 0, isTextBox: true });
    s.addText("Come meet Dyno, Sage & Penny", { x: 0.7, y: 1.15, w: 11.9, h: 1.0, fontSize: 40, bold: true, fontFace: THEME.headFontFace,
      color: C.background1, margin: 0, valign: "middle", isTextBox: true });
    const next = [
      [I.bolt, C.accent1, "Snappier", "LiteRT-LM on a Jetson: published benchmarks show the first word in about 0.9 s."],
      [I.cubes, C.accent2, "A bigger cast", "Every new friend is the same thin client. Just add a toy."],
      [I.hand, C.accent3, "More ways to play", "A motion sensor in every toy: shake, tilt and high-five games."],
    ];
    next.forEach(([ic, col, head, body], i) => {
      const x = 0.7 + i * 4.1;
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 2.6, w: 3.8, h: 2.55, rectRadius: 0.2, fill: { color: "2A2F66" }, line: { type: "none" },
        objectName: head + " card" });
      badge(s, ic, x + 0.3, 2.9, 0.8, col, head);
      s.addText(head, { x: x + 1.25, y: 2.9, w: 2.4, h: 0.8, fontSize: 20, bold: true, color: C.background1, valign: "middle", margin: 0, isTextBox: true });
      s.addText(body, { x: x + 0.3, y: 3.9, w: 3.2, h: 1.1, fontSize: 15, color: "D9DAF0", valign: "top", margin: 0, isTextBox: true });
    });
    badge(s, I.github, 0.7, 5.75, 0.6, "2A2F66", "github");
    s.addText("github.com/patrick-hanley/sentient", { x: 1.45, y: 5.75, w: 6.5, h: 0.6, fontSize: 18, color: C.background1, valign: "middle",
      margin: 0, isTextBox: true, hyperlink: { url: "https://github.com/patrick-hanley/sentient" } });
    s.addText("Thank you. Ask Penny a times-table question.", { x: 7.2, y: 5.75, w: 5.45, h: 0.6, fontSize: 16, italic: true, color: C.accent1,
      align: "right", valign: "middle", margin: 0, isTextBox: true });
    s.addNotes("Where it goes next: on a Jetson with LiteRT-LM, published benchmarks put Gemma's first word at under a second. The cast can grow, since every new friend is just another thin client. And each Atom already has a motion sensor, so shake, tilt and high-five games are next. The code is public on GitHub. Thank you! Come ask Penny a times-table question.");
  }

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})().catch((e) => { console.error(e); process.exit(1); });
