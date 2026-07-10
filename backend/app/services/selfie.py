from __future__ import annotations

from io import BytesIO
from statistics import mean, pstdev

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

from app.models.schemas import FraudSignal, SelfieAnalysisRequest
from app.services.face_biometrics import OpenCvFaceRecognizer, PassiveSpoofAnalyzer

FACE_MATCH_PASS_THRESHOLD = 0.68
FACE_MATCH_BORDERLINE_THRESHOLD = 0.74
# Below this face-width/frame-width ratio the PAD models are unreliable and
# strongly biased toward spoof, so small-face frames are excluded from the
# model vote and a mostly-small burst is asked to move closer instead.
MIN_FACE_WIDTH_RATIO = 0.22


def _clamp(value: float) -> float:
    return max(0.0, min(value, 1.0))


def _signal(code: str, label: str, severity: str, score: float) -> FraudSignal:
    return FraudSignal(code=code, label=label, severity=severity, score=round(_clamp(score), 2))


class SelfieAnalyzer:
    """Selfie quality, passive liveness, and face verification."""

    def __init__(
        self,
        face_recognizer: OpenCvFaceRecognizer | None = None,
        passive_spoof: PassiveSpoofAnalyzer | None = None,
    ) -> None:
        self.face_recognizer = face_recognizer or OpenCvFaceRecognizer()
        self.passive_spoof = passive_spoof or PassiveSpoofAnalyzer()

    def analyze(self, content: bytes, filename: str, reference_embedding: list[float] | None = None) -> SelfieAnalysisRequest:
        signals: list[FraudSignal] = []
        try:
            raw = Image.open(BytesIO(content))
            image = ImageOps.exif_transpose(raw).convert("RGB")
        except UnidentifiedImageError:
            return SelfieAnalysisRequest(
                passive_liveness_passed=False,
                face_match_score=0.0,
                passive_liveness_risk=1.0,
                selfie_quality_score=0.0,
                selfie_checks={"filename": filename},
                selfie_signals=[_signal("SELFIE_NOT_IMAGE", "Selfie upload is not a readable image.", "high", 1.0)],
            )

        width, height = image.size
        pixels = width * height
        gray = ImageOps.grayscale(image)
        frame_stat = ImageStat.Stat(gray)
        frame_brightness = frame_stat.mean[0]
        sharpness = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0]
        center_skin_ratio = self._center_skin_ratio(image)

        # Detect the face first. In dark/backlit captures the detector often
        # misses the face, so when the first pass fails (or the frame is
        # under-exposed) we retry on an illumination-normalized copy. That copy
        # only changes intensity/colour, not geometry, so the returned box stays
        # valid for the original image (used below for PAD and face metering),
        # while the rescued embedding is measured off the better-lit face.
        face_result = self.face_recognizer.extract(content, "selfie")
        embedding_source = "original"
        if face_result.face_box is None or face_result.embedding is None or frame_brightness < 90:
            rescued = self.face_recognizer.extract(self._encode_jpeg(self._normalize_illumination(image)), "selfie")
            box_a, box_b = face_result.face_box, rescued.face_box
            improved = (
                (box_a is None and box_b is not None)
                or (face_result.embedding is None and rescued.embedding is not None)
                or (box_a is not None and box_b is not None and box_b[2] * box_b[3] > box_a[2] * box_a[3] * 1.05)
            )
            if improved:
                face_result = rescued
                embedding_source = "illumination_normalized"
        signals.extend(face_result.signals)

        # #1 Face-region metering: measure lighting on the face, not the frame.
        brightness, contrast, glare_ratio = self._face_region_metrics(image, gray, face_result.face_box)

        quality = 0.24
        quality += 0.2 if pixels >= 450_000 else 0.08 if pixels >= 220_000 else 0.0
        quality += 0.18 if 55 <= brightness <= 220 else 0.04
        quality += 0.18 if contrast >= 24 else 0.07 if contrast >= 16 else 0.0
        quality += 0.16 if sharpness >= 7 else 0.08 if sharpness >= 3.2 else 0.0
        quality += 0.14 if center_skin_ratio >= 0.08 else 0.0
        quality += 0.1 if glare_ratio <= 0.12 else 0.0
        quality = _clamp(quality)

        if pixels < 220_000:
            signals.append(_signal("SELFIE_LOW_RESOLUTION", "Selfie resolution is too low.", "high", 0.76))
        if brightness < 45 or brightness > 235:
            signals.append(_signal("SELFIE_POOR_LIGHTING", "Selfie lighting is too dark or overexposed.", "medium", 0.5))
        elif face_result.face_box is not None and brightness < 80 and (frame_brightness - brightness) > 45:
            signals.append(_signal("SELFIE_FACE_UNDEREXPOSED", "Your face is in shadow or backlit. Face a light source and keep bright windows or lamps out of the background.", "medium", 0.4))
        if contrast < 16:
            signals.append(_signal("SELFIE_LOW_CONTRAST", "Selfie contrast is too low for reliable analysis.", "medium", 0.42))
        if sharpness < 1.4:
            signals.append(_signal("SELFIE_BLUR_DETECTED", "Selfie is too blurry for reliable analysis.", "high", 0.78))
        elif sharpness < 3.2:
            signals.append(_signal("SELFIE_LOW_SHARPNESS", "Selfie sharpness is low; face-match confidence may be reduced.", "medium", 0.28))
        if center_skin_ratio < 0.04:
            signals.append(_signal("FACE_NOT_CENTERED", "A face-like region was not detected near the center.", "high", 0.72))
        elif center_skin_ratio < 0.08:
            signals.append(_signal("FACE_CENTER_WEAK", "Face appears weak or off-center.", "medium", 0.36))
        if glare_ratio > 0.18:
            signals.append(_signal("SELFIE_GLARE_OR_SCREEN_RISK", "Strong glare may indicate a screen replay or poor capture.", "medium", 0.48))

        face_width_ratio = 0.0
        if face_result.face_box and width:
            face_width_ratio = face_result.face_box[2] / width
            if face_width_ratio < MIN_FACE_WIDTH_RATIO:
                signals.append(
                    _signal(
                        "SELFIE_FACE_TOO_SMALL",
                        "You are a bit too far from the camera; move your face closer until it fills the yellow circle.",
                        "medium",
                        0.2,
                    )
                )

        passive_result = self.passive_spoof.analyze(content, face_result.face_box)
        signals.extend(passive_result.signals)

        face_match_score = 0.0
        if reference_embedding is None:
            signals.append(_signal("PASSPORT_FACE_REFERENCE_MISSING", "Passport face embedding is missing; selfie cannot be matched.", "high", 0.92))
        elif face_result.embedding is not None:
            face_match_score = self.face_recognizer.compare(reference_embedding, face_result.embedding)
            if face_match_score < FACE_MATCH_PASS_THRESHOLD:
                signals.append(_signal("FACE_MATCH_LOW", "Selfie face does not match the passport portrait.", "high", 1 - face_match_score))
            elif face_match_score < FACE_MATCH_BORDERLINE_THRESHOLD:
                signals.append(_signal("FACE_MATCH_BORDERLINE", "Selfie face match is borderline.", "medium", 1 - face_match_score))

        quality_passive_risk = _clamp(
            (1 - quality) * 0.55
            + glare_ratio * 0.35
            + (0.18 if center_skin_ratio < 0.08 else 0)
            + sum(signal.score * (0.28 if signal.severity == "medium" else 0.48) for signal in signals)
        )
        passive_risk = max(quality_passive_risk, passive_result.risk)
        hard_fail = any(signal.severity == "high" for signal in signals)
        passed = (
            not hard_fail
            and passive_result.passed
            and passive_risk <= 0.5
            and quality >= 0.46
            and face_match_score >= FACE_MATCH_PASS_THRESHOLD
        )

        return SelfieAnalysisRequest(
            passive_liveness_passed=passed,
            face_match_score=round(face_match_score, 2),
            passive_liveness_risk=round(passive_risk, 2),
            selfie_quality_score=round(quality, 2),
            selfie_checks={
                "filename": filename,
                "width": width,
                "height": height,
                "megapixels": round(pixels / 1_000_000, 2),
                "brightness": round(brightness, 2),
                "frame_brightness": round(frame_brightness, 2),
                "selfie_embedding_source": embedding_source,
                "contrast": round(contrast, 2),
                "sharpness": round(sharpness, 2),
                "center_skin_ratio": round(center_skin_ratio, 4),
                "glare_ratio": round(glare_ratio, 4),
                "selfie_face_width_ratio": round(face_width_ratio, 4),
                "face_match_model": "opencv_yunet_sface",
                "face_match_threshold": FACE_MATCH_PASS_THRESHOLD,
                "face_match_borderline_threshold": FACE_MATCH_BORDERLINE_THRESHOLD,
                "face_match_score_raw": round(face_match_score, 4),
                "passport_face_reference_available": reference_embedding is not None,
                **face_result.checks,
                **passive_result.checks,
            },
            selfie_signals=signals,
        )

    def analyze_frames(self, contents: list[bytes], filenames: list[str], reference_embedding: list[float] | None = None) -> SelfieAnalysisRequest:
        frames = [(content, filenames[index] if index < len(filenames) else f"selfie-frame-{index}.jpg") for index, content in enumerate(contents) if content]
        if not frames:
            return self.analyze(b"", "selfie-empty-burst.jpg", reference_embedding)
        if len(frames) == 1:
            analysis = self.analyze(frames[0][0], frames[0][1], reference_embedding)
            analysis.selfie_checks = {**analysis.selfie_checks, "selfie_burst_frame_count": 1, "selfie_burst_mode": "single_frame"}
            return analysis

        analyses = [self.analyze(content, filename, reference_embedding) for content, filename in frames]
        representative_index, representative = max(
            enumerate(analyses),
            key=lambda item: (
                item[1].selfie_quality_score or 0.0,
                item[1].face_match_score or 0.0,
                -(item[1].passive_liveness_risk or 1.0),
            ),
        )

        temporal_checks = self._temporal_burst_checks([content for content, _ in frames])
        frame_risks = [analysis.passive_liveness_risk or 1.0 for analysis in analyses]
        screen_frame_scores = [self._float_check(analysis.selfie_checks, "passive_spoof_screen_frame_score") for analysis in analyses]
        display_surface_scores = [self._float_check(analysis.selfie_checks, "passive_spoof_display_surface_score") for analysis in analyses]
        paper_photo_scores = [self._float_check(analysis.selfie_checks, "passive_spoof_paper_photo_score") for analysis in analyses]
        held_phone_scores = [self._float_check(analysis.selfie_checks, "passive_spoof_held_phone_score") for analysis in analyses]
        model_risks = [self._float_check(analysis.selfie_checks, "passive_spoof_model_risk") for analysis in analyses]
        display_like_scores = [
            max(screen_score, display_score, paper_score)
            for screen_score, display_score, paper_score in zip(screen_frame_scores, display_surface_scores, paper_photo_scores, strict=False)
        ]
        display_like_count = sum(
            1
            for screen_score, display_score, paper_score in zip(screen_frame_scores, display_surface_scores, paper_photo_scores, strict=False)
            if screen_score >= 0.42 or display_score >= 0.58 or paper_score >= 0.38
        )
        display_like_ratio = display_like_count / max(len(analyses), 1)
        held_phone_count = sum(score >= 0.42 for score in held_phone_scores)
        held_phone_ratio = held_phone_count / max(len(held_phone_scores), 1)
        # Overexposure / strong backlight washes out the face and pushes the PAD
        # model toward a false spoof verdict. Detect it so we can give the user
        # actionable lighting guidance instead of an unhelpful "replay" message.
        brightness_vals = [self._float_check(analysis.selfie_checks, "passive_spoof_face_brightness") for analysis in analyses]
        glare_vals = [self._float_check(analysis.selfie_checks, "passive_spoof_glare_ratio") for analysis in analyses]
        avg_brightness = sum(brightness_vals) / max(len(brightness_vals), 1)
        avg_glare = sum(glare_vals) / max(len(glare_vals), 1)
        lighting_too_bright = avg_brightness >= 150 or avg_glare >= 0.05 or max(glare_vals, default=0.0) >= 0.2
        face_width_ratios = [self._float_check(analysis.selfie_checks, "selfie_face_width_ratio") for analysis in analyses]
        adequate_face_indices = [index for index, ratio_value in enumerate(face_width_ratios) if ratio_value >= MIN_FACE_WIDTH_RATIO]
        small_face_count = len(analyses) - len(adequate_face_indices)
        # PAD model output on small/distant faces is unreliable and biased
        # toward spoof, so only frames with an adequate face size vote.
        reliable_model_risks = [model_risks[index] for index in adequate_face_indices] or model_risks
        max_reliable_model_risk = max(reliable_model_risks, default=0.0)
        model_high_count = sum(risk >= 0.72 for risk in reliable_model_risks)
        model_high_ratio = model_high_count / max(len(reliable_model_risks), 1)
        model_very_high_count = sum(risk >= 0.85 for risk in reliable_model_risks)
        # A genuine replay keeps the PAD model risk high across MOST of the burst.
        # A real face under backlight/glasses/phone-camera can spike on a couple of
        # frames — so require a sustained majority (not just 2 noisy frames) before
        # the model alone hard-fails, unless the model is very confident (>=0.85).
        model_spoof_recurring = (
            (model_high_count >= 3 and model_high_ratio >= 0.4)
            or model_very_high_count >= 2
        )
        # Frame-level aggregate/heuristic codes are replaced by burst-level
        # equivalents, which vote over reliable frames (with corroboration) instead
        # of letting one frame hard-fail the burst. Held-phone is included here
        # because it false-fires on real selfies (glasses/reflections) that have a
        # LOW model risk; the burst logic below only fails it when corroborated.
        frame_aggregate_codes = {
            "PASSIVE_SPOOF_RISK_HIGH",
            "PAD_MODEL_SPOOF_HIGH",
            "SELFIE_HELD_PHONE_SCREEN",
            "SELFIE_POSSIBLE_HELD_PHONE_SCREEN",
        }
        strong_frame_signals = [
            signal
            for analysis in analyses
            for signal in analysis.selfie_signals
            if signal.severity == "high" and signal.code not in frame_aggregate_codes
        ]

        burst_signals = self._dedupe_signals(representative.selfie_signals)
        burst_signals = [signal for signal in burst_signals if signal.code not in frame_aggregate_codes]
        if temporal_checks["selfie_burst_static_replay"] >= 1:
            burst_signals.append(_signal("SELFIE_BURST_STATIC_REPLAY", "Selfie burst has almost no natural frame-to-frame motion or lighting change.", "high", 0.86))
        if display_like_ratio >= 0.45:
            burst_signals.append(_signal("SELFIE_BURST_DISPLAY_REPLAY", "Display or tablet replay cues recur across the selfie burst.", "high", max(display_like_scores)))
        # Held-phone only hard-fails when corroborated — a real phone replay also
        # keeps the PAD model risk elevated (>=0.5), whereas a real face that trips
        # the held-phone heuristic keeps a low model risk. Very strong held-phone
        # evidence (>=0.82) or a display/tablet cue also confirms it.
        held_phone_recurring = held_phone_count >= 2 or held_phone_ratio >= 0.25
        held_phone_confirmed = held_phone_recurring and (
            max_reliable_model_risk >= 0.5
            or max(held_phone_scores, default=0.0) >= 0.82
            or display_like_ratio >= 0.45
        )
        if held_phone_confirmed:
            burst_signals.append(_signal("SELFIE_BURST_HELD_PHONE_REPLAY", "Held-phone replay cues recur across the selfie burst.", "high", max(held_phone_scores)))
        if small_face_count * 2 > len(analyses):
            burst_signals.append(_signal("SELFIE_BURST_FACE_TOO_SMALL", "You are a bit too far from the camera. Move your face closer until it fills the yellow circle, then capture again.", "high", 0.7))
        if model_spoof_recurring:
            burst_signals.append(_signal("SELFIE_BURST_MODEL_SPOOF_HIGH", "Anti-spoofing model detected recurring spoof risk across the selfie burst.", "high", max(reliable_model_risks)))
        # Lighting hint (medium — does not by itself fail): surfaced so the UI can
        # tell a genuine user to fix bright/backlit conditions rather than showing a
        # confusing "replay" message.
        if lighting_too_bright:
            burst_signals.append(_signal("SELFIE_LIGHTING_TOO_BRIGHT", "Strong light or a bright background is washing out the selfie; move to softer, even lighting.", "medium", 0.4))
        burst_signals = self._dedupe_signals([*burst_signals, *strong_frame_signals])

        max_frame_risk = max(frame_risks, default=1.0)
        has_hard_replay_cue = any(signal.severity == "high" for signal in burst_signals)
        representative_frame_risk = representative.passive_liveness_risk or 1.0
        frame_risk_for_burst = max_frame_risk if has_hard_replay_cue else min(max_frame_risk, 0.48)
        representative_risk_for_burst = representative_frame_risk if has_hard_replay_cue else min(representative_frame_risk, 0.48)
        max_model_risk = max(reliable_model_risks, default=0.0)
        model_risk_for_burst = max_model_risk if model_spoof_recurring else min(max_model_risk, 0.48)
        burst_risk = max(
            representative_risk_for_burst,
            frame_risk_for_burst,
            0.86 if temporal_checks["selfie_burst_static_replay"] >= 1 else 0.0,
            0.86 if display_like_ratio >= 0.45 else 0.0,
            0.88 if held_phone_confirmed else 0.0,
            model_risk_for_burst,
        )
        hard_fail = any(signal.severity == "high" for signal in burst_signals)
        passed = (
            not hard_fail
            and burst_risk <= 0.5
            and (representative.face_match_score or 0.0) >= FACE_MATCH_PASS_THRESHOLD
        )

        representative.selfie_checks = {
            **representative.selfie_checks,
            "selfie_burst_mode": "multi_frame",
            "selfie_burst_frame_count": len(frames),
            "selfie_burst_representative_frame": representative_index,
            "selfie_burst_max_passive_risk": round(max_frame_risk, 3),
            "selfie_burst_mean_passive_risk": round(mean(frame_risks), 3),
            "selfie_burst_display_like_count": display_like_count,
            "selfie_burst_display_like_ratio": round(display_like_ratio, 3),
            "selfie_burst_held_phone_count": held_phone_count,
            "selfie_burst_held_phone_ratio": round(held_phone_ratio, 3),
            "selfie_burst_max_display_surface_score": round(max(display_like_scores, default=0.0), 3),
            "selfie_burst_max_held_phone_score": round(max(held_phone_scores, default=0.0), 3),
            "selfie_burst_max_model_risk": round(max_model_risk, 3),
            "selfie_burst_model_high_count": model_high_count,
            "selfie_burst_model_high_ratio": round(model_high_ratio, 3),
            "selfie_burst_small_face_count": small_face_count,
            "selfie_burst_model_reliable_frame_count": len(reliable_model_risks),
            **temporal_checks,
        }
        representative.passive_liveness_passed = passed
        representative.passive_liveness_risk = round(burst_risk, 2)
        representative.selfie_signals = burst_signals
        return representative

    @staticmethod
    def _float_check(checks: dict[str, float | int | str | bool | None], key: str) -> float:
        value = checks.get(key)
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return 0.0
        return 0.0

    @staticmethod
    def _dedupe_signals(signals: list[FraudSignal]) -> list[FraudSignal]:
        severity_rank = {"low": 0, "medium": 1, "high": 2}
        by_code: dict[str, FraudSignal] = {}
        for signal in signals:
            current = by_code.get(signal.code)
            if (
                current is None
                or severity_rank[signal.severity] > severity_rank[current.severity]
                or signal.score > current.score
            ):
                by_code[signal.code] = signal
        return list(by_code.values())

    @staticmethod
    def _temporal_burst_checks(contents: list[bytes]) -> dict[str, float | int | bool]:
        thumbnails = []
        brightness_values = []
        for content in contents:
            try:
                image = ImageOps.exif_transpose(Image.open(BytesIO(content))).convert("RGB")
            except UnidentifiedImageError:
                continue
            gray = ImageOps.grayscale(image).resize((128, 96))
            thumbnails.append(gray)
            brightness_values.append(ImageStat.Stat(gray).mean[0])

        deltas = []
        for previous, current in zip(thumbnails, thumbnails[1:]):
            delta = ImageChops.difference(previous, current)
            deltas.append(ImageStat.Stat(delta).mean[0])

        mean_delta = mean(deltas) if deltas else 0.0
        brightness_std = pstdev(brightness_values) if len(brightness_values) > 1 else 0.0
        static_replay = len(thumbnails) >= 4 and mean_delta < 0.55 and brightness_std < 0.28
        return {
            "selfie_burst_readable_frame_count": len(thumbnails),
            "selfie_burst_mean_frame_delta": round(mean_delta, 3),
            "selfie_burst_brightness_std": round(brightness_std, 3),
            "selfie_burst_static_replay": static_replay,
        }

    @staticmethod
    def _center_skin_ratio(image: Image.Image) -> float:
        width, height = image.size
        crop = image.crop((int(width * 0.28), int(height * 0.18), int(width * 0.72), int(height * 0.72))).resize((180, 220))
        total = crop.width * crop.height
        skin = 0
        for red, green, blue in crop.getdata():
            if red > 60 and green > 35 and blue > 25 and red > blue and red >= green * 0.82 and max(red, green, blue) - min(red, green, blue) > 12:
                skin += 1
        return skin / max(total, 1)

    @staticmethod
    def _glare_ratio(image: Image.Image) -> float:
        hsv = image.convert("HSV").resize((240, max(1, round(240 / (image.width / max(image.height, 1))))))
        total = hsv.width * hsv.height
        glare = 0
        for _, sat, val in hsv.getdata():
            if val >= 245 and sat <= 32:
                glare += 1
        return glare / max(total, 1)

    @staticmethod
    def _face_region_metrics(
        image: Image.Image, gray: Image.Image, face_box: tuple[int, int, int, int] | None
    ) -> tuple[float, float, float]:
        """Brightness, contrast and glare metered on the face crop, not the whole
        frame. A bright window behind a dark face (backlit) reads "fine"
        frame-wide but fails the face -- this measures what actually matters.
        Falls back to whole-frame metrics when no face box is available."""
        if face_box is None:
            stat = ImageStat.Stat(gray)
            return stat.mean[0], stat.stddev[0], SelfieAnalyzer._glare_ratio(image)
        x, y, w, h = face_box
        pad_x, pad_y = int(w * 0.1), int(h * 0.1)
        left, top = max(0, x - pad_x), max(0, y - pad_y)
        right, bottom = min(image.width, x + w + pad_x), min(image.height, y + h + pad_y)
        if right <= left or bottom <= top:
            stat = ImageStat.Stat(gray)
            return stat.mean[0], stat.stddev[0], SelfieAnalyzer._glare_ratio(image)
        face_gray = gray.crop((left, top, right, bottom))
        stat = ImageStat.Stat(face_gray)
        return stat.mean[0], stat.stddev[0], SelfieAnalyzer._glare_ratio(image.crop((left, top, right, bottom)))

    @staticmethod
    def _normalize_illumination(image: Image.Image) -> Image.Image:
        """Illumination normalization for low-light / colour-cast rescue:
        gray-world white balance + CLAHE on luminance + a gamma pull toward
        mid-tone. Near-identity for a well-exposed frame, so it only meaningfully
        changes the dark/backlit captures it is meant to rescue."""
        try:
            import cv2
            import numpy as np
        except ImportError:
            return ImageOps.autocontrast(image.convert("RGB"))
        arr = np.asarray(image.convert("RGB")).astype(np.float32)
        channel_means = arr.reshape(-1, 3).mean(axis=0)
        gray_mean = float(channel_means.mean())
        balanced = np.clip(arr * (gray_mean / np.clip(channel_means, 1.0, None)), 0, 255).astype(np.uint8)
        lab = cv2.cvtColor(balanced, cv2.COLOR_RGB2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        l_channel = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l_channel)
        out = cv2.cvtColor(cv2.merge((l_channel, a_channel, b_channel)), cv2.COLOR_LAB2RGB)
        mean_l = float(l_channel.mean()) / 255.0
        if 0.02 < mean_l < 0.95:
            exponent = float(np.clip(np.log(0.5) / np.log(mean_l), 0.45, 2.2))
            lut = (np.clip((np.arange(256) / 255.0) ** exponent, 0, 1) * 255).astype(np.uint8)
            out = lut[out]
        return Image.fromarray(out)

    @staticmethod
    def _encode_jpeg(image: Image.Image) -> bytes:
        buffer = BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=92)
        return buffer.getvalue()
