Attribute VB_Name = "JPCITE"
'==============================================================================
' jpcite.bas — Excel user-defined functions (UDFs) for jpcite REST API
'------------------------------------------------------------------------------
' Operator: Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708)
' Brand:    jpcite (https://jpcite.com)
' API:      https://api.jpcite.com  (X-API-Key header, ¥3/req metered)
'
' Five UDFs are exposed to the worksheet:
'   =JPCITE_HOUJIN(houjin_bangou)        -> 法人名 + 住所 (single string)
'   =JPCITE_HOUJIN_FULL(houjin_bangou)   -> JSON 全体 (raw response string)
'   =JPCITE_PROGRAMS(query)              -> 上位 5 制度 (newline-joined)
'   =JPCITE_LAW(law_id)                  -> 法令名 + 効力日
'   =JPCITE_ENFORCEMENT(houjin_bangou)   -> 行政処分有無 ("該当あり/なし")
'
' Reading the API key:
'   Priority 1: cell named "APIKey" on sheet "Settings"
'   Priority 2: env var %JPCITE_API_KEY% (Windows)
' If neither is set, every UDF returns "#NEEDS_KEY".
'
' COST WARNING:
'   Every cell call = 1 request = ¥3 (税込 ¥3.30).
'   Excel auto-recalc can fan out to (cells × recalcs) × ¥3 very quickly.
'   See README.md "Recalc storm" section before deploying to a workbook with
'   thousands of rows.
'==============================================================================
Option Explicit

Private Const JPCITE_API_BASE   As String = "https://api.jpcite.com"
Private Const JPCITE_USER_AGENT As String = "jpcite-xlam/0.3.2 (Excel)"
Private Const JPCITE_TIMEOUT_MS As Long   = 15000


'------------------------------------------------------------------------------
' Public UDFs
'------------------------------------------------------------------------------

Public Function JPCITE_HOUJIN(ByVal houjin_bangou As String) As String
Attribute JPCITE_HOUJIN.VB_Description = "法人番号から法人名+住所を取得 (¥3/req)"
    Application.Volatile False
    Dim raw As String
    raw = jpcite_get("/v1/houjin/" & url_encode(houjin_bangou), "")
    If left_n(raw, 1) = "#" Then
        JPCITE_HOUJIN = raw
        Exit Function
    End If
    Dim name_s As String, addr_s As String
    name_s = json_string(raw, "name")
    If LenB(name_s) = 0 Then name_s = json_string(raw, "houjin_name")
    addr_s = json_string(raw, "address")
    If LenB(addr_s) = 0 Then addr_s = json_string(raw, "houjin_address")
    JPCITE_HOUJIN = trim_join(name_s, addr_s, " / ")
End Function


Public Function JPCITE_HOUJIN_FULL(ByVal houjin_bangou As String) As String
Attribute JPCITE_HOUJIN_FULL.VB_Description = "法人番号の全フィールドを JSON 文字列で返す (¥3/req)"
    Application.Volatile False
    JPCITE_HOUJIN_FULL = jpcite_get("/v1/houjin/" & url_encode(houjin_bangou), "")
End Function


Public Function JPCITE_PROGRAMS(ByVal query As String, _
                                Optional ByVal limit As Long = 5) As String
Attribute JPCITE_PROGRAMS.VB_Description = "制度検索: 上位 N 件を改行で連結して返す (¥3/req)"
    Application.Volatile False
    If limit < 1 Then limit = 1
    If limit > 20 Then limit = 20
    Dim raw As String
    raw = jpcite_get("/v1/programs/search", _
                     "q=" & url_encode(query) & "&limit=" & CStr(limit))
    If left_n(raw, 1) = "#" Then
        JPCITE_PROGRAMS = raw
        Exit Function
    End If
    JPCITE_PROGRAMS = json_array_field_join(raw, "results", "name", vbLf)
End Function


Public Function JPCITE_LAW(ByVal law_id As String) As String
Attribute JPCITE_LAW.VB_Description = "法令ID から名称+効力日 (¥3/req)"
    Application.Volatile False
    Dim raw As String
    raw = jpcite_get("/v1/laws/" & url_encode(law_id), "")
    If left_n(raw, 1) = "#" Then
        JPCITE_LAW = raw
        Exit Function
    End If
    Dim title_s As String, eff_s As String
    title_s = json_string(raw, "title")
    If LenB(title_s) = 0 Then title_s = json_string(raw, "name")
    eff_s = json_string(raw, "effective_date")
    If LenB(eff_s) = 0 Then eff_s = json_string(raw, "effective_from")
    JPCITE_LAW = trim_join(title_s, eff_s, " / ")
End Function


Public Function JPCITE_ENFORCEMENT(ByVal houjin_bangou As String) As String
Attribute JPCITE_ENFORCEMENT.VB_Description = "法人番号の行政処分有無 (¥3/req)"
    Application.Volatile False
    Dim raw As String
    raw = jpcite_get("/v1/am/enforcement", "houjin_bangou=" & url_encode(houjin_bangou))
    If left_n(raw, 1) = "#" Then
        JPCITE_ENFORCEMENT = raw
        Exit Function
    End If
    Dim cnt_s As String
    cnt_s = json_string(raw, "all_count")
    If LenB(cnt_s) = 0 Then cnt_s = "0"
    If cnt_s = "0" Then
        JPCITE_ENFORCEMENT = "該当なし"
    Else
        JPCITE_ENFORCEMENT = "該当あり (" & cnt_s & " 件)"
    End If
End Function


'------------------------------------------------------------------------------
' Private helpers
'------------------------------------------------------------------------------

Private Function jpcite_get(ByVal path_s As String, _
                            ByVal query_s As String) As String
    On Error GoTo http_err

    Dim api_key As String
    api_key = jpcite_resolve_api_key()
    If LenB(api_key) = 0 Then
        jpcite_get = "#NEEDS_KEY"
        Exit Function
    End If

    Dim url As String
    url = JPCITE_API_BASE & path_s
    If LenB(query_s) > 0 Then url = url & "?" & query_s

    Dim http As Object
    Set http = CreateObject("MSXML2.XMLHTTP.6.0")
    http.Open "GET", url, False
    http.setRequestHeader "X-API-Key", api_key
    http.setRequestHeader "Accept", "application/json"
    http.setRequestHeader "User-Agent", JPCITE_USER_AGENT
    http.send

    If http.Status >= 200 And http.Status < 300 Then
        jpcite_get = CStr(http.responseText)
    ElseIf http.Status = 401 Or http.Status = 403 Then
        jpcite_get = "#AUTH_ERROR (" & CStr(http.Status) & ")"
    ElseIf http.Status = 429 Then
        jpcite_get = "#RATE_LIMITED"
    ElseIf http.Status = 404 Then
        jpcite_get = "#NOT_FOUND"
    Else
        jpcite_get = "#HTTP_" & CStr(http.Status)
    End If
    Exit Function

http_err:
    jpcite_get = "#NETWORK_ERROR"
End Function


Private Function jpcite_resolve_api_key() As String
    Dim key_s As String
    key_s = ""

    ' Priority 1: named cell APIKey on Settings sheet
    On Error Resume Next
    Dim r As Range
    Set r = ThisWorkbook.Names("APIKey").RefersToRange
    If Not r Is Nothing Then key_s = CStr(r.Value)
    Set r = Nothing
    Err.Clear
    On Error GoTo 0

    If LenB(key_s) > 0 Then
        jpcite_resolve_api_key = Trim$(key_s)
        Exit Function
    End If

    ' Priority 2: env var
    On Error Resume Next
    key_s = Environ$("JPCITE_API_KEY")
    On Error GoTo 0
    jpcite_resolve_api_key = Trim$(key_s)
End Function


' Minimal JSON string-field extractor.
' Looks for "<field>"\s*:\s*"value" and returns value with basic escape handling.
Private Function json_string(ByVal blob As String, ByVal field_s As String) As String
    Dim needle As String
    needle = """" & field_s & """"
    Dim pos As Long
    pos = InStr(1, blob, needle, vbBinaryCompare)
    If pos = 0 Then
        json_string = ""
        Exit Function
    End If

    Dim colon_pos As Long
    colon_pos = InStr(pos + Len(needle), blob, ":", vbBinaryCompare)
    If colon_pos = 0 Then
        json_string = ""
        Exit Function
    End If

    ' Skip whitespace + opening quote (or capture numeric/null token)
    Dim i As Long
    i = colon_pos + 1
    Do While i <= Len(blob)
        Dim c As String
        c = Mid$(blob, i, 1)
        If c <> " " And c <> vbTab And c <> vbCr And c <> vbLf Then Exit Do
        i = i + 1
    Loop

    If i > Len(blob) Then
        json_string = ""
        Exit Function
    End If

    If Mid$(blob, i, 1) = """" Then
        ' string token
        i = i + 1
        Dim sb As String
        sb = ""
        Do While i <= Len(blob)
            Dim ch As String
            ch = Mid$(blob, i, 1)
            If ch = "\" And i < Len(blob) Then
                Dim nxt As String
                nxt = Mid$(blob, i + 1, 1)
                Select Case nxt
                    Case """": sb = sb & """": i = i + 2
                    Case "\":  sb = sb & "\":  i = i + 2
                    Case "/":  sb = sb & "/":  i = i + 2
                    Case "n":  sb = sb & vbLf: i = i + 2
                    Case "t":  sb = sb & vbTab: i = i + 2
                    Case "r":  sb = sb & vbCr: i = i + 2
                    Case "u"
                        If i + 5 <= Len(blob) Then
                            Dim hex_s As String
                            hex_s = Mid$(blob, i + 2, 4)
                            sb = sb & ChrW(CLng("&H" & hex_s))
                            i = i + 6
                        Else
                            i = i + 2
                        End If
                    Case Else
                        sb = sb & nxt
                        i = i + 2
                End Select
            ElseIf ch = """" Then
                Exit Do
            Else
                sb = sb & ch
                i = i + 1
            End If
        Loop
        json_string = sb
    Else
        ' bare token (number / true / false / null) -> read until comma/brace
        Dim start_pos As Long
        start_pos = i
        Do While i <= Len(blob)
            Dim cc As String
            cc = Mid$(blob, i, 1)
            If cc = "," Or cc = "}" Or cc = "]" Or cc = vbCr Or cc = vbLf Then Exit Do
            i = i + 1
        Loop
        json_string = Trim$(Mid$(blob, start_pos, i - start_pos))
        If json_string = "null" Then json_string = ""
    End If
End Function


' Walks the array under "<arr_field>" and joins inner "<inner_field>" string values.
' Honest scope: works for the API's documented array shape
'   { "<arr_field>": [ {"<inner_field>": "...", ...}, ... ] }
' For arbitrary nesting, prefer JPCITE_HOUJIN_FULL + native LAMBDA / Power Query.
Private Function json_array_field_join(ByVal blob As String, _
                                       ByVal arr_field As String, _
                                       ByVal inner_field As String, _
                                       ByVal sep As String) As String
    Dim needle As String
    needle = """" & arr_field & """"
    Dim pos As Long
    pos = InStr(1, blob, needle, vbBinaryCompare)
    If pos = 0 Then
        json_array_field_join = ""
        Exit Function
    End If

    Dim lb As Long
    lb = InStr(pos, blob, "[", vbBinaryCompare)
    If lb = 0 Then
        json_array_field_join = ""
        Exit Function
    End If

    Dim depth As Long
    depth = 1
    Dim j As Long
    j = lb + 1
    Dim arr_end As Long
    arr_end = 0
    Do While j <= Len(blob)
        Dim cc As String
        cc = Mid$(blob, j, 1)
        If cc = "[" Then
            depth = depth + 1
        ElseIf cc = "]" Then
            depth = depth - 1
            If depth = 0 Then
                arr_end = j
                Exit Do
            End If
        End If
        j = j + 1
    Loop
    If arr_end = 0 Then
        json_array_field_join = ""
        Exit Function
    End If

    Dim arr_blob As String
    arr_blob = Mid$(blob, lb, arr_end - lb + 1)

    Dim out As String
    out = ""
    Dim cursor As Long
    cursor = 1
    Dim probe As String
    probe = """" & inner_field & """"
    Do
        Dim hit As Long
        hit = InStr(cursor, arr_blob, probe, vbBinaryCompare)
        If hit = 0 Then Exit Do
        Dim val_s As String
        val_s = json_string(Mid$(arr_blob, hit), inner_field)
        If LenB(val_s) > 0 Then
            If LenB(out) = 0 Then
                out = val_s
            Else
                out = out & sep & val_s
            End If
        End If
        cursor = hit + Len(probe)
    Loop
    json_array_field_join = out
End Function


Private Function url_encode(ByVal s As String) As String
    ' Conservative percent-encoding for query/path components.
    ' Uses UTF-8 byte expansion so 日本語 round-trips on Windows + Mac Excel.
    Dim i As Long, ch As String, code As Long
    Dim sb As String
    sb = ""
    For i = 1 To Len(s)
        ch = Mid$(s, i, 1)
        code = AscW(ch)
        If code < 0 Then code = code + 65536
        If (code >= AscW("0") And code <= AscW("9")) _
           Or (code >= AscW("A") And code <= AscW("Z")) _
           Or (code >= AscW("a") And code <= AscW("z")) _
           Or ch = "-" Or ch = "_" Or ch = "." Or ch = "~" Then
            sb = sb & ch
        Else
            sb = sb & utf8_percent(ch)
        End If
    Next i
    url_encode = sb
End Function


Private Function utf8_percent(ByVal ch As String) As String
    Dim cp As Long
    cp = AscW(ch)
    If cp < 0 Then cp = cp + 65536

    Dim out As String
    out = ""
    If cp < &H80& Then
        out = "%" & Right$("0" & Hex$(cp), 2)
    ElseIf cp < &H800& Then
        out = "%" & Right$("0" & Hex$(&HC0& Or (cp \ &H40&)), 2)
        out = out & "%" & Right$("0" & Hex$(&H80& Or (cp And &H3F&)), 2)
    Else
        out = "%" & Right$("0" & Hex$(&HE0& Or (cp \ &H1000&)), 2)
        out = out & "%" & Right$("0" & Hex$(&H80& Or ((cp \ &H40&) And &H3F&)), 2)
        out = out & "%" & Right$("0" & Hex$(&H80& Or (cp And &H3F&)), 2)
    End If
    utf8_percent = out
End Function


Private Function trim_join(ByVal a As String, ByVal b As String, ByVal sep As String) As String
    If LenB(a) = 0 Then
        trim_join = b
    ElseIf LenB(b) = 0 Then
        trim_join = a
    Else
        trim_join = a & sep & b
    End If
End Function


Private Function left_n(ByVal s As String, ByVal n As Long) As String
    If LenB(s) = 0 Then
        left_n = ""
    Else
        left_n = Left$(s, n)
    End If
End Function
