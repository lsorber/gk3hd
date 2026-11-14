package org.gk3hd.standalone;

public final class NativeConsoleKeysTests {
    public static void main(String[] args) {
        int checks=0;
        for(char c:"SetLocationTime(\"LBY\",\"110a\");R25RC1CallSheep(\"r25_all\",\"GraceStartSidney\");CutToCameraAngleX(-90.0,0.0,401.65,72.31,254.96);".toCharArray()) {
            String key=NativeConsoleKeys.key(c);
            if(!key.startsWith("KEY_")||NativeConsoleKeys.shift(c)!=
                ((c>='A'&&c<='Z')||c=='"'||c=='('||c==')'||c=='_'))throw new AssertionError("Stroke "+c);
            checks++;
        }
        if(!NativeConsoleKeys.key('(').equals("KEY_9")||!NativeConsoleKeys.key(')').equals("KEY_0")||
            !NativeConsoleKeys.key('"').equals("KEY_APOSTROPHE")||!NativeConsoleKeys.key(';').equals("KEY_SEMICOLON")||!NativeConsoleKeys.key('_').equals("KEY_MINUS")||!NativeConsoleKeys.key('.').equals("KEY_PERIOD")||!NativeConsoleKeys.key('-').equals("KEY_MINUS")||NativeConsoleKeys.shift('-')||NativeConsoleKeys.shift('.'))throw new AssertionError("Punctuation");
        for(char c:new char[]{'\0','\n','é'}) {
            try {NativeConsoleKeys.key(c);throw new AssertionError("Unsupported character accepted");}
            catch(IllegalArgumentException expected){checks++;}
        }
        System.out.println((checks+1)+" bounded physical console-key checks passed");
    }
}
