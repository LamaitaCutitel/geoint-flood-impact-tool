from __future__ import annotations

import json

from branca.element import MacroElement
from jinja2 import Template


SWIPE_CONTROL_STATUS = "indisponibil pana la selectarea scenelor"


def swipe_ready(before_scene: dict | None, after_scene: dict | None) -> bool:
    return bool(before_scene and after_scene)


class SarSwipeControl(MacroElement):
    _template = Template(
        """
        {% macro html(this, kwargs) %}
        <style>
          .impact-swipe-divider {
            background:#fff; box-shadow:0 0 0 1px #0f172a;
            cursor:ew-resize; pointer-events:auto; position:absolute;
            top:0; bottom:0; width:4px; z-index:650; touch-action:none;
          }
          .impact-swipe-label {
            background:rgba(15,23,42,.88); border-radius:4px; color:#fff;
            font:700 11px/1 sans-serif; padding:6px 8px; pointer-events:none;
            position:absolute; top:12px; z-index:651;
          }
        </style>
        {% endmacro %}
        {% macro script(this, kwargs) %}
        (function () {
          var map = {{ this._parent.get_name() }};
          var config = {{ this.config_json }};
          if (!config.before || !config.after) return;
          if (!map.getPane('impactSwipeBefore')) map.createPane('impactSwipeBefore');
          if (!map.getPane('impactSwipeAfter')) map.createPane('impactSwipeAfter');
          var beforePane = map.getPane('impactSwipeBefore');
          var afterPane = map.getPane('impactSwipeAfter');
          beforePane.style.zIndex = 410;
          afterPane.style.zIndex = 420;

          if (map._impactSarSwipe) map._impactSarSwipe.remove();
          var beforeLayer = L.tileLayer(config.before, {
            attribution:'Google Earth Engine', pane:'impactSwipeBefore'
          }).addTo(map);
          var afterLayer = L.tileLayer(config.after, {
            attribution:'Google Earth Engine', pane:'impactSwipeAfter'
          }).addTo(map);

          var container = map.getContainer();
          container.querySelectorAll(
            '.impact-sar-swipe-divider,.impact-sar-swipe-label'
          ).forEach(function (element) { element.remove(); });
          var divider = L.DomUtil.create('div', 'impact-swipe-divider', container);
          divider.classList.add('impact-sar-swipe-divider');
          divider.setAttribute('aria-label', 'Comparatie BEFORE AFTER');
          divider.setAttribute('role', 'separator');
          var beforeLabel = L.DomUtil.create('div', 'impact-swipe-label', container);
          var afterLabel = L.DomUtil.create('div', 'impact-swipe-label', container);
          beforeLabel.classList.add('impact-sar-swipe-label');
          afterLabel.classList.add('impact-sar-swipe-label');
          beforeLabel.innerHTML = 'BEFORE';
          afterLabel.innerHTML = 'AFTER';
          beforeLabel.style.left = '12px';
          afterLabel.style.right = '12px';
          var splitPercent = 50;
          var errorMessage = L.DomUtil.create(
            'div', 'impact-swipe-label impact-sar-swipe-label', container
          );
          errorMessage.style.display = 'none';
          errorMessage.style.left = '50%';
          errorMessage.style.transform = 'translateX(-50%)';
          errorMessage.style.top = '48px';
          errorMessage.innerHTML = 'Imaginea nu a putut fi încărcată.';

          function update(clientX) {
            var bounds = container.getBoundingClientRect();
            splitPercent = Math.max(
              0,
              Math.min(100, ((clientX - bounds.left) / bounds.width) * 100)
            );
            syncClip();
          }
          function syncClip() {
            afterPane.style.clipPath = 'inset(0 0 0 ' + splitPercent + '%)';
            divider.style.left = 'calc(' + splitPercent + '% - 2px)';
          }
          function move(event) {
            var point = event.touches ? event.touches[0] : event;
            update(point.clientX);
            event.preventDefault();
          }
          function stop() {
            document.removeEventListener('mousemove', move);
            document.removeEventListener('mouseup', stop);
            document.removeEventListener('touchmove', move);
            document.removeEventListener('touchend', stop);
          }
          function start(event) {
            document.addEventListener('mousemove', move);
            document.addEventListener('mouseup', stop);
            document.addEventListener('touchmove', move, {passive:false});
            document.addEventListener('touchend', stop);
            move(event);
          }
          divider.addEventListener('mousedown', start);
          divider.addEventListener('touchstart', start, {passive:false});
          L.DomEvent.disableClickPropagation(divider);
          [beforeLayer, afterLayer].forEach(function (layer) {
            layer.on('tileerror', function () { errorMessage.style.display = 'block'; });
          });
          map.on('resize zoomend moveend', syncClip);
          map._impactSarSwipe = {
            remove: function () {
              map.off('resize zoomend moveend', syncClip);
              map.removeLayer(beforeLayer);
              map.removeLayer(afterLayer);
              [divider, beforeLabel, afterLabel, errorMessage].forEach(
                function (element) { if (element) element.remove(); }
              );
              afterPane.style.clipPath = '';
            }
          };
          syncClip();
        })();
        {% endmacro %}
        """
    )

    def __init__(self, before_tile: str, after_tile: str) -> None:
        super().__init__()
        self._name = "SarSwipeControl"
        self.config_json = json.dumps({"before": before_tile, "after": after_tile})


class LayerCompareControl(MacroElement):
    _template = Template(
        r"""
        {% macro html(this, kwargs) %}
        <style>
          .impact-swipe-divider {
            background:#fff; box-shadow:0 0 0 1px #0f172a;
            cursor:ew-resize; pointer-events:auto; position:absolute;
            top:0; bottom:0; width:4px; z-index:650; touch-action:none;
          }
          .impact-layer-compare-panel {
            background:#fff; color:#111827; display:none; padding:8px;
            width:230px; box-shadow:0 1px 5px rgba(0,0,0,.35);
          }
          .impact-layer-compare-panel select,
          .impact-layer-compare-panel button { width:100%; margin-top:5px; }
          .impact-compare-message { font:12px/1.3 sans-serif; margin-top:5px; }
        </style>
        {% endmacro %}
        {% macro script(this, kwargs) %}
        (function () {
          var map = {{ this._parent.get_name() }};
          var config = {{ this.config_json }};
          var currentLayers = [];
          var divider = null;
          var leftPaneName = 'impactCompareLeft';
          var rightPaneName = 'impactCompareRight';
          if (!map.getPane(leftPaneName)) map.createPane(leftPaneName);
          if (!map.getPane(rightPaneName)) map.createPane(rightPaneName);
          map.getPane(leftPaneName).style.zIndex = 430;
          map.getPane(rightPaneName).style.zIndex = 440;

          var control = L.control({position:'topleft'});
          control.onAdd = function () {
            var wrapper = L.DomUtil.create('div', 'leaflet-control');
            var button = L.DomUtil.create('button', 'leaflet-bar', wrapper);
            button.type = 'button';
            button.title = 'Compară layerele tematice';
            button.innerHTML = '↔';
            button.style.width = '34px';
            button.style.height = '34px';
            button.style.background = '#fff';
            var panel = L.DomUtil.create('div', 'impact-layer-compare-panel', wrapper);
            var preset = L.DomUtil.create('select', '', panel);
            [
              ['', 'Alege preset'],
              ['sar_water_before|sar_water_after', 'SAR BEFORE ↔ SAR AFTER'],
              ['dynamic_world_before|dynamic_world_after', 'Dynamic World BEFORE ↔ Dynamic World AFTER'],
              ['sar_new_water|dynamic_world_new_water', 'Apă nouă SAR ↔ apă nouă Dynamic World'],
              ['basemap_satellite|sar_new_water', 'Satelit ↔ apă nouă SAR']
            ].forEach(function (item) {
              var option = document.createElement('option');
              option.value = item[0]; option.textContent = item[1]; preset.appendChild(option);
            });
            var left = L.DomUtil.create('select', '', panel);
            var right = L.DomUtil.create('select', '', panel);
            Object.keys(config.layers).forEach(function (id) {
              [left, right].forEach(function (select) {
                var option = document.createElement('option');
                option.value = id; option.textContent = config.layers[id].name;
                select.appendChild(option);
              });
            });
            left.value = config.left;
            right.value = config.right;
            var activate = L.DomUtil.create('button', '', panel);
            activate.type = 'button'; activate.textContent = 'Activează';
            var swap = L.DomUtil.create('button', '', panel);
            swap.type = 'button'; swap.textContent = 'Inversează stânga / dreapta';
            var close = L.DomUtil.create('button', '', panel);
            close.type = 'button'; close.textContent = 'Închide';
            var message = L.DomUtil.create('div', 'impact-compare-message', panel);

            function clearComparison() {
              currentLayers.forEach(function (layer) { map.removeLayer(layer); });
              currentLayers = [];
              if (divider) { divider.remove(); divider = null; }
              map.getPane(rightPaneName).style.clipPath = '';
              map.off('resize zoomend moveend', syncComparison);
            }
            var splitPercent = 50;
            function syncComparison() {
              if (!divider) return;
              map.getPane(rightPaneName).style.clipPath =
                'inset(0 0 0 ' + splitPercent + '%)';
              divider.style.left = 'calc(' + splitPercent + '% - 2px)';
            }
            function update(clientX) {
              if (!divider) return;
              var container = map.getContainer();
              var bounds = container.getBoundingClientRect();
              splitPercent = Math.max(0, Math.min(100, ((clientX - bounds.left) / bounds.width) * 100));
              syncComparison();
            }
            function activateComparison() {
              clearComparison();
              var leftItem = config.layers[left.value];
              var rightItem = config.layers[right.value];
              var validUrl = function (item) {
                return item && typeof item.url === 'string' && /^https?:\/\//.test(item.url);
              };
              if (!validUrl(leftItem) || !validUrl(rightItem)) {
                message.textContent = 'Comparator indisponibil: ambele straturi trebuie să aibă un URL de tile valid.';
                return;
              }
              message.textContent = '';
              currentLayers = [
                L.tileLayer(leftItem.url, {attribution:leftItem.attribution || '', pane:leftPaneName}).addTo(map),
                L.tileLayer(rightItem.url, {attribution:rightItem.attribution || '', pane:rightPaneName}).addTo(map)
              ];
              currentLayers.forEach(function (layer) {
                layer.once('tileerror', function () {
                  message.textContent = 'Un strat nu a putut fi încărcat. Verifică serviciul de tile-uri și reîncearcă.';
                });
              });
              var container = map.getContainer();
              divider = L.DomUtil.create('div', 'impact-swipe-divider', container);
              divider.setAttribute('role', 'separator');
              function move(event) {
                var point = event.touches ? event.touches[0] : event;
                update(point.clientX); event.preventDefault();
              }
              function stop() {
                document.removeEventListener('mousemove', move);
                document.removeEventListener('mouseup', stop);
                document.removeEventListener('touchmove', move);
                document.removeEventListener('touchend', stop);
              }
              function start(event) {
                document.addEventListener('mousemove', move);
                document.addEventListener('mouseup', stop);
                document.addEventListener('touchmove', move, {passive:false});
                document.addEventListener('touchend', stop);
                move(event);
              }
              divider.addEventListener('mousedown', start);
              divider.addEventListener('touchstart', start, {passive:false});
              map.on('resize zoomend moveend', syncComparison);
              syncComparison();
            }
            button.onclick = function () {
              panel.style.display = panel.style.display === 'block' ? 'none' : 'block';
            };
            preset.onchange = function () {
              if (!preset.value) return;
              var pair = preset.value.split('|');
              left.value = pair[0]; right.value = pair[1];
            };
            activate.onclick = activateComparison;
            swap.onclick = function () {
              var previousLeft = left.value;
              left.value = right.value;
              right.value = previousLeft;
              activateComparison();
            };
            close.onclick = function () { clearComparison(); panel.style.display = 'none'; };
            L.DomEvent.disableClickPropagation(wrapper);
            if (config.active) activateComparison();
            return wrapper;
          };
          control.addTo(map);
        })();
        {% endmacro %}
        """
    )

    def __init__(
        self,
        layers: dict[str, dict[str, str]],
        left_id: str,
        right_id: str,
        active: bool = False,
    ) -> None:
        super().__init__()
        self._name = "LayerCompareControl"
        self.config_json = json.dumps(
            {
                "layers": layers,
                "left": left_id,
                "right": right_id,
                "active": bool(active),
            },
            ensure_ascii=False,
        )
