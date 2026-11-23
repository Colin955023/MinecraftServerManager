Minecraft Server Manager
Copyright (C) 2025-2026 Minecraft Server Manager Team
Copyright (C) 2025-2026 Colin955023

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

This program incorporates work covered by the following copyright and
permission notices. Because it includes GPL-3.0-only code, the program as a
whole is conveyed under GPL-3.0-only.

---

## Prism Launcher (`src/MinecraftServerManager.Domain/Mods/FlexVersion.cs`)

`FlexVersion.cs` is a C# translation and modification of `launcher/Version.h`
and `launcher/Version.cpp` from Prism Launcher
(<https://github.com/PrismLauncher/PrismLauncher>, GPL-3.0-only).
Changes: translated from C++ to C#; module version-string normalization
(`NormalizeModVersionString`) added.

    Prism Launcher - Minecraft Launcher
    Copyright (C) 2023 flowln <flowlnlnln@gmail.com>
    Copyright (C) 2022 Sefa Eyeoglu <contact@scrumplex.net>
    Copyright (c) 2026 Trial97 <alexandru.tripon97@gmail.com>

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, version 3.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.

The update-check flow (resolving only missing required dependencies of the new
versions and treating installed dependencies as satisfied) follows the behavior
of Prism Launcher's mod update dialog. No code was copied for it; it is
credited here as a courtesy.

---

## Bundled third-party components

The single-file self-contained executable bundles the following components,
each distributed under its own license:

| Component | License |
| --- | --- |
| .NET Runtime | MIT (<https://github.com/dotnet/runtime/blob/main/LICENSE.TXT>) |
| CommunityToolkit.Mvvm | MIT (<https://github.com/CommunityToolkit/dotnet/blob/main/License.md>) |
| Microsoft.Extensions.Logging.Abstractions, Microsoft.Extensions.DependencyInjection.Abstractions | MIT (<https://github.com/dotnet/runtime/blob/main/LICENSE.TXT>) |
| Microsoft.Windows.CsWinRT | MIT (<https://github.com/microsoft/CsWinRT/blob/master/LICENSE>) |
| Microsoft.WindowsAppSDK.WinUI, Microsoft.WindowsAppSDK.Runtime | Microsoft Software License Terms (<https://www.nuget.org/packages/Microsoft.WindowsAppSDK/License>) |
