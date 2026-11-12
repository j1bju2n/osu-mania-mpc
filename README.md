# Osu!Mania MPC — osu!mania 맵팩 제작 도구

osu!(stable)에서 **지금 고른 맵**을 그대로 받아 와서 배속을 정해 하나씩 팩에 넣고, 썸네일을 한 번에 통일하고,
메타데이터를 맞춘 뒤 업로드할 수 있는 맵셋 폴더(.osz 선택)로 내보내는 Windows 프로그램입니다. osu!mania 전용입니다.
Made by Tamania / Claude를 사용하여 제작했습니다.

비공식 도구입니다. ppy Pty Ltd 및 osu! 팀과 관계가 없습니다.

## 다운로드
[Releases](../../releases)에서 `Osu-Mania-MPC-vX.Y.Z-win-x64.zip`을 받아 압축을 풀고 `Osu!Mania MPC.exe`를 실행하면 됩니다
(설치 없음, Windows 10/11, Microsoft Edge 또는 Chrome 필요). `ffmpeg.exe`는 반드시 같은 폴더에 두세요.
처음 실행할 때 Windows SmartScreen 경고가 뜨면 `추가 정보 → 실행`을 누르세요 (서명되지 않은 개인 배포 프로그램이라 뜨는 안내입니다).
자세한 사용법은 zip 안의 `README.txt`([docs/README.txt](docs/README.txt))에 있습니다.

**English:** Osu!Mania MPC builds osu!mania map packs. It follows the beatmap selected in osu! stable, lets you add maps
one by one at any rate (0.50–2.00, pitch kept or changed), shows an estimated difficulty (dan) for each so no map sticks
out of the pack, gives every difficulty a matching 16:9 thumbnail from one design, unifies the metadata, adds the
`[delete]` marathon difficulty, and exports a ready-to-upload folder with every track converted to mp3 without moving
the offset. It also has a rate changer for single maps and a rebuild mode that updates an already uploaded set under
its original BeatmapSetID. The interface is Korean. Unofficial; not affiliated with ppy Pty Ltd.

## 기능
- **맵 고르기**: osu!에서 고른 맵이 자동으로 뜹니다. 배속은 0.01 단위, 피치 유지 / 배속에 따라 변경.
  예상 난이도(단)는 참고용이며 팩 안에서 난이도가 튀는 맵을 막는 데 씁니다.
- **팩 구성**: 맵마다 단위인정 위치를 그래프로 보고 순서를 정리합니다.
- **썸네일**: 16:9 고정. 심볼·글자·이미지·도형을 자유롭게 배치하고, 노이즈·흐림·색 입히기 등 효과를 모든 맵에 한 번에 적용합니다.
  "이 맵만 다르게", 효과 아래로 내리는 레이어, 색마다 그라디언트, 커스텀 심볼을 지원합니다.
- **메타데이터**: 팩 이름·태그 통일, 맵별 난이도명, 맵별 태그, 미업로드 상태로 되돌리기, `[delete]` 난이도 자동 추가.
- **레이트 체인저**: 맵 하나를 여러 배속(또는 BPM)으로 한 번에 만듭니다.
- **기존 맵팩 수정**: 이미 올린 맵셋을 불러와 맵을 갈아끼우거나 썸네일을 통일하고, 같은 BeatmapSetID로 업데이트할 수정본을 만듭니다.
- **저장 / 불러오기**: 팩 구성을 `save` 폴더의 `.mpcpack` 파일로 저장합니다.

## 업로드 순서
[delete]난이도를 반드시 먼저 업로드 해주세요. 그래야 썸네일 및 맵팩의 미리듣기 재생구간이 먼저 설정됩니다. 그 후에 나머지 난이도들을 다시 넣고 [delete]난이도에 들어가서 맵을 업데이트 해주세요.

## 오프셋
모든 음원은 44.1kHz mp3로 바뀝니다. 
1.00배속 mp3는 그대로 복사하고, 변환과 피치 변경 배속은 샘플 단위로 맞으며(0.02ms)
피치 유지 배속은 맵마다 밀린 오디오를 바로잡은 뒤 남은 오차를 결과 화면에 보여 줍니다(보통 1ms 이내).
osu! 폴더는 읽기만 하고, 외부로 아무것도 내보내지않습니다.

## 개발
Python 3.13, 표준 라이브러리만 사용합니다. 화면은 127.0.0.1 서버 + Edge/Chrome 앱 창입니다.
Claude Fable 5.2 모델을 사용해 제작되었습니다.

```
python tests/test_core.py
python tests/test_edit.py
python tests/test_rate.py
python tests/test_app.py
powershell -ExecutionPolicy Bypass -File build.ps1
```

테스트는 이 PC의 osu! 폴더에 있는 실제 맵과 `ffmpeg.exe`가 필요합니다. 빌드는 PyInstaller가 필요하고 결과는 `output/`에 생깁니다.
`src/mpc/bin/mmr-calc.exe`는 Mania Tracker의 dan-calc를 `tools/build_calc.ps1`로 빌드한 것입니다.

## 사용한 것
- 예상 난이도 계산과 단 심볼: [Mania Tracker](https://github.com/aleju03/mania-hub) (MIT, © 2026 aleju03).
  dan-calc에는 LeoBlack의 osumania_map_analyser (MIT), Etterna의 MinaCalc (MIT) 등이 들어 있습니다.
  단 심볼이 나타내는 단위인정 코스는 각 코스 제작자의 것입니다: 4K Dan ~ REFORM ~ (Thaumiel), 4K LN v2 (_underjoy),
  7K (Jinjin), 6K (Arkman), 6K LN ([Crz]sunnyxxy). 심볼을 빼기를 원하는 코스 제작자는 이슈로 알려 주세요.
- 오디오 변환: [FFmpeg](https://ffmpeg.org) (GPL v3, gyan.dev 빌드). 릴리스 zip에 `ffmpeg.exe`가 수정 없이 따로 들어 있으며
  별도 프로그램으로 실행됩니다. 소스는 ffmpeg.org와 gyan.dev 빌드 페이지에 있습니다. GPL은 `ffmpeg.exe`에만 적용됩니다.
- osu!에서 고른 맵을 읽는 메모리 위치는 [tosu](https://github.com/tosuapp/tosu)가 공개한 정보를 참고했습니다 (코드는 가져오지 않았습니다).
- Python, PyInstaller.

전체 고지문은 [docs/NOTICE.txt](docs/NOTICE.txt), [src/mpc/bin/THIRD-PARTY-LICENSES.txt](src/mpc/bin/THIRD-PARTY-LICENSES.txt),
[src/mpc/web/dans/LICENSE.txt](src/mpc/web/dans/LICENSE.txt)에 있고, 릴리스 zip의 `licenses` 폴더에도 들어 있습니다.
