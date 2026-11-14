package com.winlator;

import android.os.Bundle;

/** Explicit backend entry after checked launcher selection, or with a developer container. */
public final class OpenXrActivity extends StandaloneGameActivity {
    @Override public void onCreate(Bundle state) {
        getIntent().putExtra("gk3hd_xr_presenter","openxr");
        super.onCreate(state);
    }
}
