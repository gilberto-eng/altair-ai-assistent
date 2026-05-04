import os
import threading
from typing import Any, Callable, Dict, List, Optional


def _safe_float(value: Any, default: float) -> float:
    try:
        if isinstance(value, dict):
            value = value.get("default", default)
        return float(value)
    except Exception:
        return float(default)


def _export_to_stl(result: Any, path: str) -> None:
    from cadquery import exporters
    try:
        import cadquery as cq
        if isinstance(result, cq.Assembly):
            try:
                result = result.toCompound()
            except Exception:
                pass
        if isinstance(result, cq.Workplane):
            try:
                result = result.findSolid()
            except Exception:
                pass
            try:
                result = result.val()
            except Exception:
                pass
    except Exception:
        pass

    exporters.export(result, path)


def abrir_viewer_parametrico(
    *,
    build_fn: Callable[[Dict[str, float]], Any],
    params: List[Dict[str, Any]],
    output_dir: str,
    title: str = "Altair CAD Viewer",
) -> Optional[str]:
    try:
        import pyvista as pv
    except Exception as exc:
        return f"pyvistaqt nao esta disponivel: {exc}"

    os.makedirs(output_dir, exist_ok=True)
    stl_path = os.path.join(output_dir, "preview.stl")

    params_current: Dict[str, float] = {}
    for p in params:
        nome = str(p.get("name", "")).strip()
        if not nome:
            continue
        params_current[nome] = _safe_float(p.get("default", 1.0), 1.0)

    def rebuild(plotter: Any) -> None:
        try:
            result = build_fn(params_current)
            _export_to_stl(result, stl_path)
            mesh = pv.read(stl_path)
            if getattr(plotter, "_cad_actor", None) is None:
                plotter._cad_actor = plotter.add_mesh(mesh, color="#c7d1ff", show_edges=True)
            else:
                plotter._cad_actor.mapper.SetInputData(mesh)
                plotter._cad_actor.mapper.Update()
            plotter.render()
        except Exception:
            return

    def _run_viewer() -> None:
        plotter: Any
        use_background = threading.current_thread() is threading.main_thread()
        if use_background:
            try:
                from pyvistaqt import BackgroundPlotter
                from qtpy import QtWidgets
                plotter = BackgroundPlotter(title=title)
            except Exception:
                use_background = False
        if not use_background:
            plotter = pv.Plotter(title=title)

        plotter.add_axes()
        rebuild(plotter)

        if use_background:
            # Menu lateral Qt para parametros.
            dock = QtWidgets.QDockWidget("Parametros", plotter.app_window)
            dock.setAllowedAreas(QtWidgets.Qt.LeftDockWidgetArea | QtWidgets.Qt.RightDockWidgetArea)
            container = QtWidgets.QWidget()
            layout = QtWidgets.QFormLayout(container)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(6)

            widgets = []
            for p in params:
                nome = str(p.get("name", "")).strip()
                if not nome:
                    continue
                minimo = _safe_float(p.get("min", 1.0), 1.0)
                maximo = _safe_float(p.get("max", minimo + 1.0), minimo + 1.0)
                passo = _safe_float(p.get("step", (maximo - minimo) / 50.0), 0.1)
                valor = _safe_float(p.get("default", minimo), minimo)
                if maximo <= minimo:
                    maximo = minimo + 1.0

                params_current[nome] = valor

                spin = QtWidgets.QDoubleSpinBox()
                spin.setRange(minimo, maximo)
                spin.setSingleStep(passo)
                spin.setValue(valor)

                def _on_change(val, key=nome) -> None:
                    params_current[key] = float(val)
                    rebuild(plotter)

                spin.valueChanged.connect(_on_change)
                layout.addRow(nome, spin)
                widgets.append(spin)

            dock.setWidget(container)
            plotter.app_window.addDockWidget(QtWidgets.Qt.LeftDockWidgetArea, dock)
            plotter._param_dock = dock
            plotter._param_widgets = widgets
        else:
            # Fallback: sliders dentro da cena 3D.
            slider_y = 0.08
            for p in params:
                nome = str(p.get("name", "")).strip()
                if not nome:
                    continue
                minimo = _safe_float(p.get("min", 1.0), 1.0)
                maximo = _safe_float(p.get("max", minimo + 1.0), minimo + 1.0)
                passo = _safe_float(p.get("step", (maximo - minimo) / 50.0), 0.1)
                valor = _safe_float(p.get("default", minimo), minimo)

                if maximo <= minimo:
                    maximo = minimo + 1.0

                params_current[nome] = valor

                def _callback(val, key=nome) -> None:
                    params_current[key] = float(val)
                    rebuild(plotter)

                try:
                    plotter.add_slider_widget(
                        _callback,
                        [minimo, maximo],
                        value=valor,
                        title=nome,
                        pointa=(0.02, slider_y),
                        pointb=(0.38, slider_y),
                        event_type="always",
                    )
                except TypeError:
                    # Compatibilidade com versoes do pyvista sem event_type.
                    plotter.add_slider_widget(
                        _callback,
                        [minimo, maximo],
                        value=valor,
                        title=nome,
                        pointa=(0.02, slider_y),
                        pointb=(0.38, slider_y),
                    )
                slider_y += 0.06

        if not use_background:
            plotter.show()

    if threading.current_thread() is threading.main_thread():
        _run_viewer()
    else:
        # Tenta agendar no main thread do Tk para habilitar o menu Qt.
        try:
            import tkinter as _tk

            root = getattr(_tk, "_default_root", None)
            if root is not None:
                root.after(0, _run_viewer)
                return None
        except Exception:
            pass
        threading.Thread(target=_run_viewer, daemon=True).start()
    return None
