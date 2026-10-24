// Copy to secrets.h and fill in. Networks are tried in order; must be 2.4 GHz.
static const WifiCred WIFI_LIST[] = {
  { "sentient-brain", "sentient123" },        // brain hotspot (tools/setup_brain.sh)
  // { "SameNameAP", "password", 11 },         // optional 3rd field: pin a channel if two APs share a name
  { "YOUR_PHONE_HOTSPOT", "YOUR_PASSWORD" },  // fallback (iPhone: Maximize Compatibility ON)
};
