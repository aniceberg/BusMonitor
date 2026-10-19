// Registers the "busmonitor:" icon set so the sidebar can show the Bus Monitor icon.
// One-colour version of the brand icon (bus front + location pin), 24x24, nonzero fill:
// holes are drawn with the opposite winding.
const BUS =
  // body (clockwise)
  "M4,7H12.5A2,2 0 0 1 14.5,9V16.5A2,2 0 0 1 12.5,18.5H4A2,2 0 0 1 2,16.5V9A2,2 0 0 1 4,7Z" +
  // windshield (hole, counter-clockwise) with a centre post (clockwise)
  "M4.3,9A0.8,0.8 0 0 0 3.5,9.8V11.7A0.8,0.8 0 0 0 4.3,12.5H12.2A0.8,0.8 0 0 0 13,11.7V9.8A0.8,0.8 0 0 0 12.2,9Z" +
  "M7.95,9H8.55V12.5H7.95Z" +
  // headlights and grille (holes)
  "M3.6,15A1.1,1.1 0 0 0 5.8,15A1.1,1.1 0 0 0 3.6,15Z" +
  "M10.7,15A1.1,1.1 0 0 0 12.9,15A1.1,1.1 0 0 0 10.7,15Z" +
  "M7,14.3V15.7H9.5V14.3Z" +
  // bumper and wheels (clockwise)
  "M2.1,17.8H14.4A0.9,0.9 0 0 1 15.3,18.7A0.9,0.9 0 0 1 14.4,19.6H2.1A0.9,0.9 0 0 1 1.2,18.7A0.9,0.9 0 0 1 2.1,17.8Z" +
  "M3,19.2H5.6V21.5H3Z" +
  "M10.9,19.2H13.5V21.5H10.9Z" +
  // location pin (clockwise) with its hole (counter-clockwise)
  "M19.2,13L15.615,7.575A4.3,4.3 0 1 1 22.785,7.575Z" +
  "M17.6,5.2A1.6,1.6 0 0 0 20.8,5.2A1.6,1.6 0 0 0 17.6,5.2Z";

const ICONS = { bus: BUS };

window.customIcons = window.customIcons || {};
window.customIcons.busmonitor = {
  getIcon: async (name) => ({ path: ICONS[name] || BUS }),
  getIconList: async () => Object.keys(ICONS).map((name) => ({ name })),
};
