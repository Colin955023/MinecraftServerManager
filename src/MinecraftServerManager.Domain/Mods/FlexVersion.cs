// SPDX-License-Identifier: GPL-3.0-only
/*
 *  Minecraft Server Manager - FlexVersion
 *  Copyright (C) 2025-2026 Colin955023
 *
 *  This file is a C# translation and modification of launcher/Version.h and
 *  launcher/Version.cpp from Prism Launcher (https://github.com/PrismLauncher/PrismLauncher),
 *  translated and modified by Colin955023 on 2026-10-14. The original work carries
 *  the following notice:
 *
 *      Prism Launcher - Minecraft Launcher
 *      Copyright (C) 2023 flowln <flowlnlnln@gmail.com>
 *      Copyright (C) 2022 Sefa Eyeoglu <contact@scrumplex.net>
 *      Copyright (c) 2026 Trial97 <alexandru.tripon97@gmail.com>
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */

namespace MinecraftServerManager.Domain.Mods;

/// <summary>彈性語意版本比較引擎（移植自 Prism Launcher Version 類別，授權與版權聲明見檔案開頭與 COPYING.md）</summary>
public sealed class FlexVersion
{
    private enum SectionType : byte
    {
        Null = 0,
        Textual = 1,
        Numeric = 2,
        PreRelease = 3,
    }

    private readonly record struct Section(SectionType Type, string Value)
    {
        public static readonly Section Null = new(SectionType.Null, string.Empty);

        public int CompareTo(Section other)
        {
            if (Type == SectionType.Numeric && other.Type == SectionType.Numeric)
            {
                if (Value.Length != other.Value.Length)
                {
                    return Value.Length.CompareTo(other.Value.Length);
                }
                return string.Compare(Value, other.Value, StringComparison.Ordinal);
            }

            if (Type == SectionType.Null && other.Type == SectionType.Null)
            {
                return 0;
            }

            // 正式版 (Null) 優先於 PreRelease 版
            if (Type == SectionType.Null)
            {
                return other.Type == SectionType.PreRelease ? 1 : -1;
            }
            if (other.Type == SectionType.Null)
            {
                return Type == SectionType.PreRelease ? -1 : 1;
            }

            return string.CompareOrdinal(Value, other.Value);
        }
    }

    private readonly List<Section> _sections;

    public FlexVersion(string? raw)
    {
        _sections = ParseSections(raw ?? string.Empty);
    }

    /// <summary>比較兩個模組版本字串之新舊先後關係</summary>
    public static int Compare(string? a, string? b)
    {
        if (string.Equals(a, b, StringComparison.OrdinalIgnoreCase))
        {
            return 0;
        }

        string cleanA = NormalizeModVersionString(a);
        string cleanB = NormalizeModVersionString(b);

        var vA = new FlexVersion(cleanA);
        var vB = new FlexVersion(cleanB);
        return vA.CompareTo(vB);
    }

    /// <summary>正規化模組版本字串（去除 v/V 與 mc1.x- 等常見前綴）</summary>
    public static string NormalizeModVersionString(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw))
        {
            return string.Empty;
        }

        ReadOnlySpan<char> span = raw.Trim().AsSpan();

        // 去除開頭的 'v' 或 'V' (若其後直接接數字，例如 v1.2.0 -> 1.2.0)
        if (span.StartsWith("v", StringComparison.OrdinalIgnoreCase) && span.Length > 1 && char.IsAsciiDigit(span[1]))
        {
            span = span[1..];
        }

        // 去除常見 Minecraft 版本前綴，如 mc1.21.1-0.15.2 或 1.21-15.1.4
        if (span.StartsWith("mc", StringComparison.OrdinalIgnoreCase) && span.Length > 2 && char.IsAsciiDigit(span[2]))
        {
            int sepIndex = span.IndexOfAny('-', '_');
            if (sepIndex > 2 && sepIndex + 1 < span.Length && char.IsAsciiDigit(span[sepIndex + 1]))
            {
                span = span[(sepIndex + 1)..];
            }
        }
        else if (char.IsAsciiDigit(span[0]))
        {
            int firstDash = span.IndexOf('-');
            if (firstDash > 0 && firstDash + 1 < span.Length && char.IsAsciiDigit(span[firstDash + 1]))
            {
                ReadOnlySpan<char> prefix = span[..firstDash];
                ReadOnlySpan<char> remainder = span[(firstDash + 1)..];
                if (prefix.StartsWith("1.") && remainder.Contains('.'))
                {
                    span = remainder;
                }
            }
        }

        return span.ToString();
    }

    private static List<Section> ParseSections(string raw)
    {
        var sections = new List<Section>();
        ReadOnlySpan<char> span = raw.AsSpan();
        int len = span.Length;

        for (int i = 0; i < len;)
        {
            char c = span[i];
            if (c == '+')
            {
                // 依照 FlexVer 規範：忽略 '+' 之後的建置中繼資料 (Build Metadata)
                break;
            }

            var type = SectionType.Textual;
            int start = i;

            if (c is '-' or ' ')
            {
                i++;
                if (i < len && !char.IsAsciiDigit(span[i]))
                {
                    type = SectionType.PreRelease;
                }
            }
            else if (char.IsAsciiDigit(c))
            {
                type = SectionType.Numeric;
            }

            while (i < len)
            {
                char r = span[i];
                if ((char.IsAsciiDigit(r) != (type == SectionType.Numeric))
                    || (r == ' ' && type == SectionType.Numeric)
                    || (r == '-' && type != SectionType.PreRelease)
                    || r == '+')
                {
                    break;
                }
                i++;
            }

            ReadOnlySpan<char> secSpan = span[start..i];
            if (!secSpan.IsEmpty)
            {
                if (type == SectionType.Numeric)
                {
                    secSpan = secSpan.TrimStart('0');
                }
                sections.Add(new Section(type, secSpan.ToString()));
            }
        }

        return sections;
    }

    public int CompareTo(FlexVersion? other)
    {
        if (ReferenceEquals(this, other))
        {
            return 0;
        }
        if (other is null)
        {
            return 1;
        }

        int maxSections = Math.Max(_sections.Count, other._sections.Count);
        for (int i = 0; i < maxSections; i++)
        {
            var secA = i < _sections.Count ? _sections[i] : Section.Null;
            var secB = i < other._sections.Count ? other._sections[i] : Section.Null;

            int cmp = secA.CompareTo(secB);
            if (cmp != 0)
            {
                return cmp;
            }
        }

        return 0;
    }
}
