# -*- coding: utf-8 -*-

import wx
import sys
import json
import os
import pcbnew

from .viastitching_gui import viastitching_gui

DEFAULTS_FILE = os.path.join(os.path.dirname(__file__), "defaults.json")

PLUGIN_GROUP_NAME = "viastitching"

# Conversion helpers
def mm2iu(mm):
    return int(pcbnew.FromMM(mm))

def iu2mm(iu):
    return pcbnew.ToMM(iu)


class viastitching_dialog(viastitching_gui):

    def __init__(self, parent, board):
        viastitching_gui.__init__(self, parent)

        self.board = board
        self.defaults = {}

        # Load defaults
        try:
            with open(DEFAULTS_FILE, "r") as f:
                self.defaults = json.load(f)
        except Exception:
            pass

        # Populate net combo
        nets = board.GetNetInfo().NetsByName()
        for net_name in sorted(nets.keys()):
            self.m_cbNet.Append(net_name)

        # Pre-select the net of the selected zone (if any)
        selected_zone = self._get_selected_zone()
        if selected_zone is not None:
            zone_net_name = selected_zone.GetNetname()
            idx = self.m_cbNet.FindString(zone_net_name)
            if idx != wx.NOT_FOUND:
                self.m_cbNet.SetSelection(idx)

        # Populate via size/drill from board design settings
        via_size = iu2mm(board.GetDesignSettings().GetCurrentViaSize())
        via_drill = iu2mm(board.GetDesignSettings().GetCurrentViaDrill())

        self.m_txtViaSize.SetValue(str(round(via_size, 4)))
        self.m_txtViaDrillSize.SetValue(str(round(via_drill, 4)))

        # Spacing / offset / clearance from defaults
        self.m_txtVSpacing.SetValue(str(self.defaults.get("vspacing", 1.6)))
        self.m_txtHSpacing.SetValue(str(self.defaults.get("hspacing", 1.6)))
        self.m_txtVOffset.SetValue(str(self.defaults.get("voffset", 0.0)))
        self.m_txtHOffset.SetValue(str(self.defaults.get("hoffset", 0.0)))
        self.m_txtClearance.SetValue(str(self.defaults.get("clearance", 0.0)))

        # Checkboxes
        self.m_chkRandomize.SetValue(self.defaults.get("randomize", False))
        self.m_chkStagger.SetValue(self.defaults.get("stagger", False))

        # Bind buttons
        self.m_btnOk.Bind(wx.EVT_BUTTON, self.onOk)
        self.m_btnCancel.Bind(wx.EVT_BUTTON, self.onCancel)
        self.m_btnClear.Bind(wx.EVT_BUTTON, self.onClear)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_selected_zone(self):
        """Return the first selected ZONE on the board, or None."""
        for item in self.board.GetSelection():
            if isinstance(item, pcbnew.ZONE):
                return item
        # Fallback: iterate all zones and find a selected one
        for zone in self.board.Zones():
            if zone.IsSelected():
                return zone
        return None

    def _read_float(self, ctrl, default=0.0):
        try:
            return float(ctrl.GetValue().replace(",", "."))
        except ValueError:
            return default

    def _save_defaults(self):
        data = {
            "vspacing":   self._read_float(self.m_txtVSpacing, 1.6),
            "hspacing":   self._read_float(self.m_txtHSpacing, 1.6),
            "voffset":    self._read_float(self.m_txtVOffset, 0.0),
            "hoffset":    self._read_float(self.m_txtHOffset, 0.0),
            "clearance":  self._read_float(self.m_txtClearance, 0.0),
            "randomize":  self.m_chkRandomize.GetValue(),
            "stagger":    self.m_chkStagger.GetValue(),
        }
        try:
            with open(DEFAULTS_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Fill logic
    # ------------------------------------------------------------------

    def FillupArea(self):
        zone = self._get_selected_zone()
        if zone is None:
            wx.MessageBox("No zone selected!\nPlease select a copper zone first.",
                          "ViaStitching", wx.OK | wx.ICON_ERROR)
            return

        # Read parameters
        net_name   = self.m_cbNet.GetValue()
        via_size   = mm2iu(self._read_float(self.m_txtViaSize))
        via_drill  = mm2iu(self._read_float(self.m_txtViaDrillSize))
        v_spacing  = mm2iu(self._read_float(self.m_txtVSpacing, 1.6))
        h_spacing  = mm2iu(self._read_float(self.m_txtHSpacing, 1.6))
        v_offset   = mm2iu(self._read_float(self.m_txtVOffset, 0.0))
        h_offset   = mm2iu(self._read_float(self.m_txtHOffset, 0.0))
        clearance  = mm2iu(self._read_float(self.m_txtClearance, 0.0))
        randomize  = self.m_chkRandomize.GetValue()
        stagger    = self.m_chkStagger.GetValue()

        net_info   = self.board.GetNetInfo()
        net        = net_info.GetNetItem(net_name)

        if net is None:
            wx.MessageBox("Net '{}' not found!".format(net_name),
                          "ViaStitching", wx.OK | wx.ICON_ERROR)
            return

        # Bounding box of the zone
        bbox = zone.GetBoundingBox()
        x_min = bbox.GetLeft()   + h_offset
        x_max = bbox.GetRight()
        y_min = bbox.GetTop()    + v_offset
        y_max = bbox.GetBottom()

        # Create a group for undo tracking
        group = pcbnew.PCB_GROUP(self.board)
        self.board.Add(group)
        group.SetName(PLUGIN_GROUP_NAME)

        via_count = 0
        row_idx   = 0
        y = y_min

        import random

        while y <= y_max:
            # Stagger: shift every odd row by half the horizontal spacing
            if stagger and (row_idx % 2 == 1):
                x_start = x_min + h_spacing // 2
            else:
                x_start = x_min

            x = x_start
            while x <= x_max:
                # Optional random jitter (small fraction of spacing)
                px = x
                py = y
                if randomize:
                    jitter_x = random.randint(-h_spacing // 8, h_spacing // 8)
                    jitter_y = random.randint(-v_spacing // 8, v_spacing // 8)
                    px += jitter_x
                    py += jitter_y

                p = pcbnew.VECTOR2I(px, py)

                # Check clearance from zone edges
                inside = zone.HitTestInsideZone(p)
                if not inside:
                    x += h_spacing
                    continue

                if clearance > 0:
                    # Check minimum distance from zone outline
                    dist = zone.GetOutline().Distance(p)
                    if dist < clearance:
                        x += h_spacing
                        continue

                # Place via
                via = pcbnew.PCB_VIA(self.board)
                via.SetPosition(p)
                via.SetWidth(via_size)
                via.SetDrill(via_drill)
                via.SetNet(net)
                via.SetViaType(pcbnew.VIATYPE_THROUGH)
                self.board.Add(via)
                group.AddItem(via)
                via_count += 1

                x += h_spacing

            y += v_spacing
            row_idx += 1

        pcbnew.Refresh()
        wx.MessageBox("Done! Placed {} via(s).".format(via_count),
                      "ViaStitching", wx.OK | wx.ICON_INFORMATION)

    def ClearArea(self):
        """Remove vias from the selected zone that match the current settings."""
        zone = self._get_selected_zone()
        if zone is None:
            wx.MessageBox("No zone selected!", "ViaStitching", wx.OK | wx.ICON_ERROR)
            return

        net_name  = self.m_cbNet.GetValue()
        via_size  = mm2iu(self._read_float(self.m_txtViaSize))
        via_drill = mm2iu(self._read_float(self.m_txtViaDrillSize))
        own_only  = self.m_chkClearOwn.GetValue()

        net_info  = self.board.GetNetInfo()
        net       = net_info.GetNetItem(net_name)

        removed = 0

        if own_only:
            # Remove only vias that belong to the plugin's group
            for group in self.board.Groups():
                if group.GetName() == PLUGIN_GROUP_NAME:
                    items = list(group.GetItems())
                    for item in items:
                        if isinstance(item, pcbnew.PCB_VIA):
                            p = item.GetPosition()
                            if zone.HitTestInsideZone(p):
                                if (net is None or item.GetNet() == net) and \
                                   item.GetWidth() == via_size and \
                                   item.GetDrill() == via_drill:
                                    self.board.Remove(item)
                                    removed += 1
                    if group.GetItems().empty():
                        self.board.Remove(group)
        else:
            vias_to_remove = []
            for track in self.board.GetTracks():
                if isinstance(track, pcbnew.PCB_VIA):
                    p = track.GetPosition()
                    if zone.HitTestInsideZone(p):
                        if (net is None or track.GetNet() == net) and \
                           track.GetWidth() == via_size and \
                           track.GetDrill() == via_drill:
                            vias_to_remove.append(track)
            for via in vias_to_remove:
                self.board.Remove(via)
                removed += 1

        pcbnew.Refresh()
        wx.MessageBox("Done! Removed {} via(s).".format(removed),
                      "ViaStitching", wx.OK | wx.ICON_INFORMATION)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def onOk(self, event):
        self._save_defaults()
        self.FillupArea()

    def onCancel(self, event):
        self.EndModal(wx.ID_CANCEL)

    def onClear(self, event):
        self._save_defaults()
        self.ClearArea()
